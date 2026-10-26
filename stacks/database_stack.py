from typing import Optional
from pathlib import Path
import json

from aws_cdk import BootstraplessSynthesizer, CfnOutput, CustomResource, Duration, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import custom_resources as cr
from aws_cdk import cloudformation_include as cfn_include
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
        active_db_host: Optional[str] = None,
        active_db_instance_identifier: Optional[str] = None,
        retired_template_path: Optional[str] = None,
        app_config_defaults: Optional[dict[str, str]] = None,
        **kwargs,
    ) -> None:
        if retired_template_path:
            # The transition template already carries its bootstrap parameter.
            kwargs.setdefault("synthesizer", BootstraplessSynthesizer())
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"

        deletion_protection = (
            bool(db_deletion_protection)
            if db_deletion_protection is not None
            else env_name == "prod"
        )
        # Even dev contains business data. Preserve the resource on deletion
        # and replacement, without changing its ID, class or engine version.
        removal_policy = RemovalPolicy.RETAIN

        self.db_security_group = db_security_group
        self.app_config_parameter_prefix = app_config_parameter_prefix.rstrip("/")

        if retired_template_path:
            # Preserve the existing subnet group, credential and parameter IDs.
            # The reviewed transition template contains no DBInstance resource,
            # so subsequent deployments cannot recreate the retired database.
            template_path = Path(__file__).resolve().parent.parent / retired_template_path
            template = json.loads(template_path.read_text())
            if any(resource["Type"] == "AWS::RDS::DBInstance"
                   for resource in template["Resources"].values()):
                raise ValueError("Retired database template must not provision a database.")
            if not active_db_host or not active_db_instance_identifier:
                raise ValueError("Retirement requires an explicit active database.")
            if template["Outputs"]["ActiveDbInstanceIdentifier"]["Value"] != active_db_instance_identifier:
                raise ValueError("Retired template does not match the active database.")
            if template["Outputs"]["ActiveDbEndpoint"]["Value"] != active_db_host:
                raise ValueError("Retired template does not match the active endpoint.")
            if template["Outputs"]["AppConfigParameterPrefix"]["Value"] != self.app_config_parameter_prefix:
                raise ValueError("Retired template belongs to a different environment.")
            cfn_include.CfnInclude(self, "RetiredDatabaseResources",
                                   template_file=str(template_path), preserve_logical_ids=True)
            self.db_instance = rds.DatabaseInstance.from_database_instance_attributes(
                self, "ActiveDatabase", instance_identifier=active_db_instance_identifier,
                instance_endpoint_address=active_db_host, port=5432,
                security_groups=[db_security_group],
            )
            return

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
        self.db_instance.secret.apply_removal_policy(RemovalPolicy.RETAIN)
        # The attached ISecret can represent the attachment, not the generated
        # secret itself. Preserve both, including the actual credential resource.
        for child in self.db_instance.node.find_all():
            if isinstance(child, secretsmanager.CfnSecret):
                child.apply_removal_policy(RemovalPolicy.RETAIN)
        # Older compute deployments still consume this export. Keep it while
        # consumers are migrated in separate, targeted deployments.
        self.export_value(self.db_instance.secret.secret_arn)
        self.export_value(self.db_instance.instance_identifier)

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
        if active_db_host:
            ssm.StringParameter(
                self, "DbHostActiveParameter",
                parameter_name=_parameter_name(self.app_config_parameter_prefix, "DB_HOST_ACTIVE"),
                string_value=active_db_host,
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
                        _parameter_name(self.app_config_parameter_prefix, "FACTURACION_CONFIG"),
                    )
                ],
            )
        )
        parameter_writer.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:PutSecretValue"],
                resources=[self.db_instance.secret.secret_arn],
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
                "DatabaseHost": self.db_instance.instance_endpoint.hostname,
                "FacturacionParameterName": _parameter_name(self.app_config_parameter_prefix, "FACTURACION_CONFIG"),
                "DbPasswordParameterName": self.app_config_parameters["DB_PASSWORD"],
                "SecretKeyParameterName": self.app_config_parameters["SECRET_KEY"],
                "DatabaseSecretKeyName": "secretKey",
                "DatabaseSecretExtraValues": app_config_defaults or {},
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
        if active_db_host:
            CfnOutput(self, "ActiveDbEndpoint", value=active_db_host)
        if active_db_instance_identifier:
            CfnOutput(self, "ActiveDbInstanceIdentifier", value=active_db_instance_identifier)
        CfnOutput(
            self,
            "AppConfigParameterPrefix",
            value=self.app_config_parameter_prefix,
        )
