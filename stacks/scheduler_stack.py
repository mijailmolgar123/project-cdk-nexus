import json
from pathlib import Path
from typing import Optional

from aws_cdk import ArnFormat, CfnOutput, Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_rds as rds
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_lambda_destinations as destinations
from aws_cdk import aws_sqs as sqs
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
        active_db_instance_identifier: Optional[str] = None,
        manage_rds: bool = True,
        rds_start_hour: int = 7,
        rds_start_minute: int = 30,
        rds_stop_minute: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"
        schedule_state = "ENABLED" if scheduler_enabled else "DISABLED"
        active_db_identifier = (
            active_db_instance_identifier or database_instance.instance_identifier
        )
        database_arns = [database_instance.instance_arn]
        if active_db_instance_identifier:
            database_arns = [self.format_arn(
                service="rds",
                resource="db",
                resource_name=active_db_identifier,
                arn_format=ArnFormat.COLON_RESOURCE_NAME,
            )]
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
                "RDS_INSTANCE_IDENTIFIER": active_db_identifier,
                "MANAGE_RDS": "true" if manage_rds else "false",
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
                resources=database_arns,
            )
        )

        invoke_role = iam.Role(
            self,
            "SchedulerInvokeRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        scheduler_function.grant_invoke(invoke_role)
        failures = sqs.Queue(
            self, "SchedulerFailures", queue_name=f"{prefix}-scheduler-failures",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(14), enforce_ssl=True,
        )
        failures.grant_send_messages(invoke_role)
        scheduler_function.configure_async_invoke(
            max_event_age=Duration.minutes(5), retry_attempts=1,
            on_failure=destinations.SqsDestination(failures),
        )
        self.failure_queue_arn = failures.queue_arn
        cloudwatch.Alarm(
            self, "SchedulerErrors", alarm_name=f"{prefix}-scheduler-errors",
            metric=scheduler_function.metric_errors(period=Duration.minutes(5)),
            threshold=1, evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        cloudwatch.Alarm(
            self, "SchedulerUndelivered", alarm_name=f"{prefix}-scheduler-undelivered",
            metric=failures.metric_approximate_number_of_messages_visible(period=Duration.minutes(5)),
            threshold=1, evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        self._schedule(
            schedule_id="BusinessHoursStart",
            description="Start ERP infrastructure for business hours.",
            name=f"{prefix}-start-business-hours",
            expression=f"cron(0 {business_start_hour} * * ? *)",
            timezone=schedule_timezone,
            state=schedule_state,
            target_arn=scheduler_function.function_arn,
            target_role_arn=invoke_role.role_arn,
            payload={"action": "start", "resource": "ec2"},
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
            payload={"action": "stop", "resource": "ec2"},
        )
        for schedule_id, name, expression, action in [
            ("DatabaseHoursStart", "start-database", f"cron({rds_start_minute} {rds_start_hour} * * ? *)", "start"),
            ("DatabaseHoursStop", "stop-database", f"cron({rds_stop_minute} {business_stop_hour} * * ? *)", "stop"),
        ]:
            self._schedule(
                schedule_id=schedule_id, description=f"{action.title()} active database around EC2 business hours.",
                name=f"{prefix}-{name}", expression=expression,
                timezone=schedule_timezone, state=schedule_state if manage_rds else "DISABLED",
                target_arn=scheduler_function.function_arn, target_role_arn=invoke_role.role_arn,
                payload={"action": action, "resource": "rds"},
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
                input=json.dumps({**payload, "scheduled_at": "<aws.scheduler.scheduled-time>"}),
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                    maximum_event_age_in_seconds=300, maximum_retry_attempts=2,
                ),
                dead_letter_config=scheduler.CfnSchedule.DeadLetterConfigProperty(
                    arn=self.failure_queue_arn,
                ),
            ),
        )
