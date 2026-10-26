"""Restore a separate RDS instance; never replace the source database."""

from datetime import datetime, timezone
import re

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_rds as rds
from constructs import Construct


class DatabaseRecoveryStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        source_instance_identifier: str,
        source_resource_id: str,
        target_instance_identifier: str,
        restore_time: str,
        db_subnet_group_name: str,
        db_security_group_ids: list[str],
        availability_zone: str,
        db_instance_class: str = "db.t4g.small",
        backup_retention_days: int = 7,
        preferred_backup_window: str = "13:30-14:00",
        preferred_maintenance_window: str = "sun:14:30-sun:15:00",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if source_instance_identifier.lower() == target_instance_identifier.lower():
            raise ValueError("Recovery must use a different DB instance identifier.")
        for identifier in (source_instance_identifier, target_instance_identifier):
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{0,62}", identifier):
                raise ValueError("Invalid DB instance identifier.")
            if identifier.endswith("-") or "--" in identifier:
                raise ValueError("Invalid DB instance identifier.")
        if not source_resource_id.startswith("db-"):
            raise ValueError("The immutable source DbiResourceId is required.")
        if not db_subnet_group_name or not db_security_group_ids:
            raise ValueError("An existing subnet group and security groups are required.")
        if not all(re.fullmatch(r"sg-[0-9a-f]+", item) for item in db_security_group_ids):
            raise ValueError("Invalid security group ID.")
        if not availability_zone.startswith(f"{self.region}"):
            raise ValueError("Recovery must stay in the source AWS Region.")
        if not re.fullmatch(r"db\.[a-z0-9]+\.[a-z0-9]+", db_instance_class):
            raise ValueError("Use the RDS class format, for example db.t4g.small.")
        if not 1 <= backup_retention_days <= 35:
            raise ValueError("Backup retention must be between 1 and 35 days.")
        restore_at = datetime.fromisoformat(restore_time.replace("Z", "+00:00"))
        if restore_at.tzinfo is None or restore_at.utcoffset() is None:
            raise ValueError("Restore time must include a timezone.")
        if restore_at > datetime.now(timezone.utc):
            raise ValueError("Restore time cannot be in the future.")

        # L1 exposes native PITR. Do not supply a new master password, DBName,
        # EngineVersion or StorageEncrypted: the source backup supplies these.
        # A fixed RestoreTime avoids silently choosing a different backup later.
        self.db_instance = rds.CfnDBInstance(
            self,
            "RecoveredDatabase",
            db_instance_identifier=target_instance_identifier,
            source_dbi_resource_id=source_resource_id,
            restore_time=restore_at.astimezone(timezone.utc).isoformat(),
            db_instance_class=db_instance_class,
            availability_zone=availability_zone,
            db_subnet_group_name=db_subnet_group_name,
            vpc_security_groups=db_security_group_ids,
            db_parameter_group_name="default.postgres17",
            publicly_accessible=False,
            multi_az=False,
            deletion_protection=True,
            backup_retention_period=backup_retention_days,
            delete_automated_backups=False,
            auto_minor_version_upgrade=True,
            preferred_backup_window=preferred_backup_window,
            preferred_maintenance_window=preferred_maintenance_window,
        )
        self.db_instance.apply_removal_policy(RemovalPolicy.RETAIN)

        CfnOutput(self, "DbEndpoint", value=self.db_instance.attr_endpoint_address)
        CfnOutput(self, "DbPort", value=self.db_instance.attr_endpoint_port)
        CfnOutput(self, "DbInstanceIdentifier", value=target_instance_identifier)
        CfnOutput(self, "SourceDbInstanceIdentifier", value=source_instance_identifier)
        CfnOutput(self, "RestoreTime", value=restore_at.isoformat())
