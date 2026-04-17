from typing import Optional
from pathlib import Path

from aws_cdk import CfnOutput, CustomResource, Duration, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_ssm as ssm
from aws_cdk import custom_resources as cr
from constructs import Construct


def _postgres_engine_version(version_str: str) -> rds.PostgresEngineVersion:
    major = version_str.split(".")[0]
    return rds.PostgresEngineVersion.of(version_str, major)


def _parameter_name(prefix: str, key: str) -> str:
    return f"{prefix.rstrip('/')}/{key}"


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
        app_config_parameter_prefix: str,
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
        self.app_config_parameter_prefix = app_config_parameter_prefix.rstrip("/")

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

        if not self.db_instance.secret:
            raise ValueError("Database secret is required to mirror credentials to SSM.")

        self.app_config_parameters = {
            "USE_AWS_SECRET": _parameter_name(
                self.app_config_parameter_prefix, "USE_AWS_SECRET"
            ),
            "DB_HOST": _parameter_name(self.app_config_parameter_prefix, "DB_HOST"),
            "DB_PORT": _parameter_name(self.app_config_parameter_prefix, "DB_PORT"),
            "DB_NAME": _parameter_name(self.app_config_parameter_prefix, "DB_NAME"),
            "DB_USER": _parameter_name(self.app_config_parameter_prefix, "DB_USER"),
            "DB_PASSWORD": _parameter_name(
                self.app_config_parameter_prefix, "DB_PASSWORD"
            ),
            "SECRET_KEY": _parameter_name(
                self.app_config_parameter_prefix, "SECRET_KEY"
            ),
        }

        ssm.StringParameter(
            self,
            "UseAwsSecretParameter",
            parameter_name=self.app_config_parameters["USE_AWS_SECRET"],
            string_value="false",
            tier=ssm.ParameterTier.STANDARD,
        )
        ssm.StringParameter(
            self,
            "DbHostParameter",
            parameter_name=self.app_config_parameters["DB_HOST"],
            string_value=self.db_instance.instance_endpoint.hostname,
            tier=ssm.ParameterTier.STANDARD,
        )
        ssm.StringParameter(
            self,
            "DbPortParameter",
            parameter_name=self.app_config_parameters["DB_PORT"],
            string_value=f"{self.db_instance.instance_endpoint.port}",
            tier=ssm.ParameterTier.STANDARD,
        )
        ssm.StringParameter(
            self,
            "DbNameParameter",
            parameter_name=self.app_config_parameters["DB_NAME"],
            string_value=db_name,
            tier=ssm.ParameterTier.STANDARD,
        )
        ssm.StringParameter(
            self,
            "DbUserParameter",
            parameter_name=self.app_config_parameters["DB_USER"],
            string_value=db_username,
            tier=ssm.ParameterTier.STANDARD,
        )

        parameter_writer = lambda_.Function(
            self,
            "AppConfigParameterWriter",
            function_name=f"{prefix}-app-config-parameter-writer",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(30),
            code=lambda_.Code.from_asset(
                str(
                    Path(__file__).resolve().parent.parent
                    / "lambda"
                    / "app_config_parameters"
                )
            ),
        )
        self.db_instance.secret.grant_read(parameter_writer)
        parameter_writer.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"],
                resources=[
                    self.format_arn(
                        service="ssm",
                        resource="parameter",
                        resource_name=name.lstrip("/"),
                    )
                    for name in (
                        self.app_config_parameters["DB_PASSWORD"],
                        self.app_config_parameters["SECRET_KEY"],
                    )
                ],
            )
        )

        parameter_writer_provider = cr.Provider(
            self,
            "AppConfigParameterWriterProvider",
            on_event_handler=parameter_writer,
        )
        mirrored_parameters = CustomResource(
            self,
            "MirroredSecureAppConfigParameters",
            service_token=parameter_writer_provider.service_token,
            properties={
                "DatabaseSecretArn": self.db_instance.secret.secret_arn,
                "DbPasswordParameterName": self.app_config_parameters["DB_PASSWORD"],
                "SecretKeyParameterName": self.app_config_parameters["SECRET_KEY"],
            },
        )
        mirrored_parameters.node.add_dependency(self.db_instance)

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
        CfnOutput(
            self,
            "DbInstanceIdentifier",
            value=self.db_instance.instance_identifier,
        )
        CfnOutput(
            self,
            "AppConfigParameterPrefix",
            value=self.app_config_parameter_prefix,
        )
