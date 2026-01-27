from typing import Optional

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct


def _postgres_engine_version(version_str: str) -> rds.PostgresEngineVersion:
    major = version_str.split(".")[0]
    return rds.PostgresEngineVersion.of(version_str, major)


class DatabaseStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        project: str,
        vpc: ec2.IVpc,
        db_security_group: ec2.ISecurityGroup,
        db_name: str,
        db_username: str,
        db_instance_class: str,
        db_allocated_storage: int,
        db_max_allocated_storage: int,
        db_backup_days: int,
        db_engine_version: str,
        db_publicly_accessible: bool,
        db_deletion_protection: Optional[bool],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"

        deletion_protection = (
            bool(db_deletion_protection)
            if db_deletion_protection is not None
            else env_name == "prod"
        )
        removal_policy = (
            RemovalPolicy.RETAIN if deletion_protection else RemovalPolicy.DESTROY
        )

        self.db_security_group = db_security_group

        self.db_instance = rds.DatabaseInstance(
            self,
            "Database",
            instance_identifier=f"{prefix}-rds",
            database_name=db_name,
            engine=rds.DatabaseInstanceEngine.postgres(
                version=_postgres_engine_version(db_engine_version)
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            instance_type=ec2.InstanceType(db_instance_class),
            credentials=rds.Credentials.from_generated_secret(
                username=db_username,
                secret_name=f"{prefix}/rds/{db_name}",
            ),
            security_groups=[self.db_security_group],
            allocated_storage=db_allocated_storage,
            max_allocated_storage=db_max_allocated_storage,
            storage_encrypted=True,
            backup_retention=Duration.days(db_backup_days),
            deletion_protection=deletion_protection,
            publicly_accessible=db_publicly_accessible,
            removal_policy=removal_policy,
            delete_automated_backups=not deletion_protection,
        )

        if self.db_instance.secret:
            CfnOutput(
                self,
                "DbSecretName",
                value=self.db_instance.secret.secret_name,
            )
        CfnOutput(
            self,
            "DbEndpoint",
            value=self.db_instance.instance_endpoint.hostname,
        )
