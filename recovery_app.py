#!/usr/bin/env python3
"""Dedicated CDK entry point: a normal app deploy never creates a recovery DB."""

from aws_cdk import App, Environment, Tags

from deployment_config import load_local_context
from stacks.database_recovery_stack import DatabaseRecoveryStack


def main() -> None:
    app = App()
    load_local_context(app)
    env_name = app.node.try_get_context("env_name") or "dev"
    env_cfg = (app.node.try_get_context("environments") or {}).get(env_name, {})
    recovery = env_cfg.get("database_recovery") or {}
    project = app.node.try_get_context("project") or "demoapp"

    def required(key: str):
        value = recovery.get(key)
        if value is None or value == "" or value == []:
            raise ValueError(f"Missing environments.{env_name}.database_recovery.{key}")
        return value

    target = required("target_instance_identifier")
    if not target.startswith(f"{project}-{env_name}-"):
        raise ValueError("Recovery target must match the chosen project and environment.")

    stack = DatabaseRecoveryStack(
        app,
        f"{project}-{env_name}-database-recovery",
        env=Environment(account=required("account"), region=env_cfg["region"]),
        stack_name=f"{project}-{env_name}-database-recovery",
        termination_protection=True,
        source_instance_identifier=required("source_instance_identifier"),
        source_resource_id=required("source_resource_id"),
        target_instance_identifier=target,
        restore_time=required("restore_time"),
        db_subnet_group_name=required("db_subnet_group_name"),
        db_security_group_ids=required("db_security_group_ids"),
        availability_zone=required("availability_zone"),
        db_instance_class=recovery.get("db_instance_class", "db.t4g.small"),
        backup_retention_days=int(recovery.get("backup_retention_days", 7)),
        preferred_backup_window=recovery.get("preferred_backup_window", "13:30-14:00"),
        preferred_maintenance_window=recovery.get("preferred_maintenance_window", "sun:14:30-sun:15:00"),
    )
    Tags.of(stack).add("project", project)
    Tags.of(stack).add("env", env_name)
    Tags.of(stack).add("purpose", "database-recovery")
    Tags.of(stack).add("created_by", "rds-oss-skill")
    Tags.of(stack).add("generation_model", "gpt-6")
    app.synth()


if __name__ == "__main__":
    main()
