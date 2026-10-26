from pathlib import Path
import subprocess
import sys
from typing import Optional

import jsii
from aws_cdk import BundlingOptions, CfnOutput, Duration, ILocalBundling, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ssm as ssm
from constructs import Construct


@jsii.implements(ILocalBundling)
class LocalPythonBundling:
    def __init__(self, asset_path: Path) -> None:
        self.asset_path = asset_path

    def try_bundle(self, output_dir: str, options: BundlingOptions) -> bool:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(self.asset_path / "requirements.txt"),
                "-t",
                output_dir,
                "--platform",
                "manylinux2014_x86_64",
                "--implementation",
                "cp",
                "--python-version",
                "3.12",
                "--abi",
                "cp312",
                "--only-binary=:all:",
            ]
        )
        subprocess.check_call(["cp", "-a", f"{self.asset_path}/.", output_dir])
        return True


class UserAdminStack(Stack):
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
        app_config_parameter_prefix: str,
        admin_schema: str,
        bundle_dependencies: bool = True,
        active_db_host: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"
        lambda_asset_path = Path(__file__).resolve().parent.parent / "lambda" / "user_admin"
        app_config_prefix = app_config_parameter_prefix.rstrip("/")
        database_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "DatabaseSecret",
            secret_name=f"{prefix}/rds/{db_name}",
        )

        lambda_security_group = ec2.SecurityGroup(
            self,
            "UserAdminLambdaSecurityGroup",
            vpc=vpc,
            security_group_name=f"{prefix}-user-admin-lambda-sg",
            allow_all_outbound=False,
        )
        lambda_security_group.add_egress_rule(
            peer=db_security_group,
            connection=ec2.Port.tcp(5432),
            description="User admin Lambda to RDS PostgreSQL",
        )

        ec2.CfnSecurityGroupIngress(
            self,
            "AllowUserAdminLambdaToDatabase",
            group_id=db_security_group.security_group_id,
            source_security_group_id=lambda_security_group.security_group_id,
            ip_protocol="tcp",
            from_port=5432,
            to_port=5432,
            description="User admin Lambda to RDS PostgreSQL",
        )

        asset_kwargs = {}
        if bundle_dependencies:
            asset_kwargs["bundling"] = BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                ],
                local=LocalPythonBundling(lambda_asset_path),
            )

        user_admin_function = lambda_.Function(
            self,
            "UserAdminFunction",
            function_name=f"{prefix}-user-admin",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(30),
            memory_size=256,
            code=lambda_.Code.from_asset(str(lambda_asset_path), **asset_kwargs),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[lambda_security_group],
            environment={
                "DB_HOST": active_db_host or ssm.StringParameter.value_for_string_parameter(
                    self, f"{app_config_prefix}/DB_HOST"
                ),
                "DB_PORT": ssm.StringParameter.value_for_string_parameter(
                    self, f"{app_config_prefix}/DB_PORT"
                ),
                "DB_NAME": db_name,
                "DB_USER": db_username,
                "DB_PASSWORD": database_secret.secret_value_from_json(
                    "password"
                ).unsafe_unwrap(),
                "DB_ADMIN_SCHEMA": admin_schema,
            },
        )

        CfnOutput(
            self,
            "UserAdminFunctionName",
            value=user_admin_function.function_name,
        )
        CfnOutput(
            self,
            "UserAdminLambdaSecurityGroupId",
            value=lambda_security_group.security_group_id,
        )
