import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk.assertions import Template
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from stacks.database_recovery_stack import DatabaseRecoveryStack


def build_recovery(**overrides):
    config = dict(
        source_instance_identifier="demoapp-dev-rds",
        source_resource_id="db-source1234",
        target_instance_identifier="demoapp-dev-rds-recovery",
        restore_time="2026-10-02T01:51:40Z",
        db_subnet_group_name="existing-private-subnets",
        db_security_group_ids=["sg-1234567890abcdef0"],
        availability_zone="us-east-1b",
    )
    config.update(overrides)
    return DatabaseRecoveryStack(
        cdk.App(), "Recovery",
        env=cdk.Environment(account="111111111111", region="us-east-1"),
        termination_protection=True,
        **config,
    )


def test_recovery_restores_backup_without_creating_credentials_or_changing_app():
    template = Template.from_stack(build_recovery())
    resources = template.to_json()["Resources"]
    db = resources["RecoveredDatabase"]
    assert db["DeletionPolicy"] == db["UpdateReplacePolicy"] == "Retain"
    assert db["Properties"]["SourceDbiResourceId"] == "db-source1234"
    assert db["Properties"]["RestoreTime"] == "2026-10-02T01:51:40+00:00"
    assert db["Properties"]["DBInstanceClass"] == "db.t4g.small"
    assert db["Properties"]["AvailabilityZone"] == "us-east-1b"
    assert db["Properties"]["DeletionProtection"] is True
    assert db["Properties"]["PubliclyAccessible"] is False
    assert db["Properties"]["BackupRetentionPeriod"] == 7
    assert db["Properties"]["PreferredBackupWindow"] == "13:30-14:00"
    assert db["Properties"]["PreferredMaintenanceWindow"] == "sun:14:30-sun:15:00"
    assert db["Properties"]["DeleteAutomatedBackups"] is False
    for inherited in ("MasterUserPassword", "MasterUsername", "DBName",
                      "EngineVersion", "StorageEncrypted", "KmsKeyId"):
        assert inherited not in db["Properties"]
    template.resource_count_is("AWS::SecretsManager::Secret", 0)
    template.resource_count_is("AWS::SSM::Parameter", 0)
    template.resource_count_is("AWS::Lambda::Function", 0)


@pytest.mark.parametrize("overrides", [
    {"target_instance_identifier": "demoapp-dev-rds"},
    {"source_resource_id": ""},
    {"restore_time": "2026-10-02T01:51:40"},
    {"restore_time": "2999-01-01T00:00:00Z"},
    {"db_security_group_ids": []},
    {"availability_zone": "us-west-2a"},
    {"backup_retention_days": 0},
])
def test_recovery_rejects_invalid_or_unsafe_configuration(overrides):
    with pytest.raises(ValueError):
        build_recovery(**overrides)
