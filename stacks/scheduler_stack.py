import json
from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_rds as rds
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct


class SchedulerStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        project: str,
        ec2_instance: ec2.IInstance,
        database_instance: rds.IDatabaseInstance,
        schedule_timezone: str,
        business_start_hour: int,
        business_stop_hour: int,
        scheduler_enabled: bool,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"
        schedule_state = "ENABLED" if scheduler_enabled else "DISABLED"
        lambda_asset_path = (
            Path(__file__).resolve().parent.parent / "lambda" / "instance_scheduler"
        )

        scheduler_function = lambda_.Function(
            self,
            "InstanceSchedulerFunction",
            function_name=f"{prefix}-instance-scheduler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset(str(lambda_asset_path)),
            timeout=Duration.seconds(30),
            environment={
                "EC2_INSTANCE_ID": ec2_instance.instance_id,
                "RDS_INSTANCE_IDENTIFIER": database_instance.instance_identifier,
            },
        )

        scheduler_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances"],
                resources=["*"],
            )
        )
        scheduler_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:StartInstances", "ec2:StopInstances"],
                resources=[
                    self.format_arn(
                        service="ec2",
                        resource="instance",
                        resource_name=ec2_instance.instance_id,
                    )
                ],
            )
        )
        scheduler_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["rds:DescribeDBInstances"],
                resources=["*"],
            )
        )
        scheduler_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["rds:StartDBInstance", "rds:StopDBInstance"],
                resources=[database_instance.instance_arn],
            )
        )

        invoke_role = iam.Role(
            self,
            "SchedulerInvokeRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        scheduler_function.grant_invoke(invoke_role)

        self._schedule(
            schedule_id="BusinessHoursStart",
            description="Start ERP infrastructure for business hours.",
            name=f"{prefix}-start-business-hours",
            expression=f"cron(0 {business_start_hour} * * ? *)",
            timezone=schedule_timezone,
            state=schedule_state,
            target_arn=scheduler_function.function_arn,
            target_role_arn=invoke_role.role_arn,
            payload={"action": "start"},
        )
        self._schedule(
            schedule_id="BusinessHoursStop",
            description="Stop ERP infrastructure after business hours.",
            name=f"{prefix}-stop-business-hours",
            expression=f"cron(0 {business_stop_hour} * * ? *)",
            timezone=schedule_timezone,
            state=schedule_state,
            target_arn=scheduler_function.function_arn,
            target_role_arn=invoke_role.role_arn,
            payload={"action": "stop"},
        )

        CfnOutput(
            self,
            "SchedulerTimezone",
            value=schedule_timezone,
        )
        CfnOutput(
            self,
            "SchedulerState",
            value=schedule_state,
        )

    def _schedule(
        self,
        *,
        schedule_id: str,
        description: str,
        name: str,
        expression: str,
        timezone: str,
        state: str,
        target_arn: str,
        target_role_arn: str,
        payload: dict,
    ) -> scheduler.CfnSchedule:
        return scheduler.CfnSchedule(
            self,
            schedule_id,
            name=name,
            description=description,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            schedule_expression=expression,
            schedule_expression_timezone=timezone,
            state=state,
            target=scheduler.CfnSchedule.TargetProperty(
                arn=target_arn,
                role_arn=target_role_arn,
                input=json.dumps(payload),
            ),
        )
