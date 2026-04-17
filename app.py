#!/usr/bin/env python3
import os
from typing import Iterable

from aws_cdk import App, Environment, Tags

from stacks.compute_stack import ComputeStack
from stacks.database_stack import DatabaseStack
from stacks.github_actions_stack import GitHubActionsStack
from stacks.network_stack import NetworkStack
from stacks.scheduler_stack import SchedulerStack


def _ctx(app: App, env_cfg: dict, key: str, default=None):
    if key in env_cfg and env_cfg[key] is not None:
        return env_cfg[key]
    value = app.node.try_get_context(key)
    if value is None:
        return default
    return value


def _required_ctx(app: App, env_cfg: dict, key: str):
    value = _ctx(app, env_cfg, key, None)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Missing required context value: {key}")
    return value


def _bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _string_list(value, default: Iterable[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return list(default)


app = App()

env_name = app.node.try_get_context("env_name") or "dev"
envs = app.node.try_get_context("environments") or {}
env_cfg = envs.get(env_name, {})
github_cfg = app.node.try_get_context("github") or {}

project = _ctx(app, env_cfg, "project", "cdk-nexus")
prefix = f"{project}-{env_name}"
app_config_parameter_prefix = _ctx(
    app,
    env_cfg,
    "app_config_parameter_prefix",
    f"/{project}/{env_name}/app-config",
)
app_directory = _ctx(app, env_cfg, "app_directory", "/home/ec2-user/app")
app_service_name = _ctx(app, env_cfg, "app_service_name", "myapp")
app_env_file_path = _ctx(app, env_cfg, "app_env_file_path", "/etc/myapp.env")
app_port = int(_ctx(app, env_cfg, "app_port", 8000))
app_system_packages = _string_list(
    _ctx(
        app,
        env_cfg,
        "app_system_packages",
        [
            "nginx",
            "git",
            "python3.11",
            "python3.11-pip",
            "postgresql17",
            "pango",
            "gdk-pixbuf2",
            "cairo",
            "fontconfig",
            "libffi",
        ],
    ),
    [],
)

account = _ctx(app, env_cfg, "account", os.getenv("CDK_DEFAULT_ACCOUNT"))
region = _ctx(app, env_cfg, "region", os.getenv("CDK_DEFAULT_REGION"))
cdk_env = Environment(account=account, region=region) if account or region else None

github_actions = GitHubActionsStack(
    app,
    f"{project}-github-actions",
    project=project,
    github_owner=github_cfg.get("owner", "your-github-org"),
    github_repo=github_cfg.get("repo", "your-github-repo"),
    github_branch=github_cfg.get("branch", "main"),
    env=cdk_env,
    stack_name=f"{project}-github-actions",
)

network = NetworkStack(
    app,
    f"{prefix}-network",
    env_name=env_name,
    project=project,
    vpc_cidr=_ctx(app, env_cfg, "vpc_cidr", "10.0.0.0/16"),
    public_subnet_cidr_mask=int(_ctx(app, env_cfg, "public_subnet_cidr_mask", 24)),
    private_subnet_cidr_mask=int(_ctx(app, env_cfg, "private_subnet_cidr_mask", 24)),
    max_azs=int(_ctx(app, env_cfg, "max_azs", 2)),
    env=cdk_env,
    stack_name=f"{prefix}-network",
)

database = DatabaseStack(
    app,
    f"{prefix}-database",
    env_name=env_name,
    project=project,
    vpc=network.vpc,
    db_security_group=network.db_security_group,
    db_name=_required_ctx(app, env_cfg, "db_name"),
    db_username=_required_ctx(app, env_cfg, "db_username"),
    db_instance_class=_ctx(app, env_cfg, "db_instance_class", "t4g.micro"),
    db_allocated_storage=int(_ctx(app, env_cfg, "db_allocated_storage", 20)),
    db_max_allocated_storage=int(_ctx(app, env_cfg, "db_max_allocated_storage", 100)),
    db_backup_days=int(_ctx(app, env_cfg, "db_backup_days", 1)),
    db_engine_version=_ctx(app, env_cfg, "db_engine_version", "17.4"),
    app_config_parameter_prefix=app_config_parameter_prefix,
    db_publicly_accessible=_bool(
        _ctx(app, env_cfg, "db_publicly_accessible", False)
    ),
    db_deletion_protection=_bool(env_cfg.get("db_deletion_protection"))
    if env_cfg.get("db_deletion_protection") is not None
    else None,
    env=cdk_env,
    stack_name=f"{prefix}-database",
)

compute = ComputeStack(
    app,
    f"{prefix}-compute",
    env_name=env_name,
    project=project,
    vpc=network.vpc,
    compute_security_group=network.compute_security_group,
    instance_type=_ctx(app, env_cfg, "instance_type", "t3.micro"),
    allow_https=_bool(_ctx(app, env_cfg, "allow_https", False)),
    ssh_cidr=_ctx(app, env_cfg, "ssh_cidr", None),
    ssh_key_name=_ctx(app, env_cfg, "ssh_key_name", None),
    app_config_parameter_prefix=app_config_parameter_prefix,
    app_directory=app_directory,
    app_service_name=app_service_name,
    app_env_file_path=app_env_file_path,
    app_port=app_port,
    bootstrap_packages=app_system_packages,
    app_deploy_key_parameter_name=_ctx(
        app, env_cfg, "app_deploy_key_parameter_name", None
    ),
    associate_elastic_ip=_bool(_ctx(app, env_cfg, "associate_elastic_ip", False)),
    env=cdk_env,
    stack_name=f"{prefix}-compute",
)

SchedulerStack(
    app,
    f"{prefix}-scheduler",
    env_name=env_name,
    project=project,
    ec2_instance=compute.instance,
    database_instance=database.db_instance,
    schedule_timezone=_ctx(app, env_cfg, "schedule_timezone", "America/Lima"),
    business_start_hour=int(_ctx(app, env_cfg, "business_start_hour", 8)),
    business_stop_hour=int(_ctx(app, env_cfg, "business_stop_hour", 21)),
    scheduler_enabled=_bool(_ctx(app, env_cfg, "scheduler_enabled", True), True),
    env=cdk_env,
    stack_name=f"{prefix}-scheduler",
)

Tags.of(app).add("project", project)
Tags.of(app).add("env", env_name)
Tags.of(github_actions).add("scope", "shared")

app.synth()
