#!/usr/bin/env python3
import os

from aws_cdk import App, Environment, Tags

from stacks.compute_stack import ComputeStack
from stacks.database_stack import DatabaseStack
from stacks.network_stack import NetworkStack


def _ctx(app: App, env_cfg: dict, key: str, default=None):
    if key in env_cfg and env_cfg[key] is not None:
        return env_cfg[key]
    value = app.node.try_get_context(key)
    if value is None:
        return default
    return value


app = App()

env_name = app.node.try_get_context("env_name") or "dev"
envs = app.node.try_get_context("environments") or {}
env_cfg = envs.get(env_name, {})

project = _ctx(app, env_cfg, "project", "cdk-nexus")
prefix = f"{project}-{env_name}"

account = _ctx(app, env_cfg, "account", os.getenv("CDK_DEFAULT_ACCOUNT"))
region = _ctx(app, env_cfg, "region", os.getenv("CDK_DEFAULT_REGION"))
cdk_env = Environment(account=account, region=region) if account or region else None

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
    db_name=_ctx(app, env_cfg, "db_name", "appdb"),
    db_username=_ctx(app, env_cfg, "db_username", "appuser"),
    db_instance_class=_ctx(app, env_cfg, "db_instance_class", "t4g.micro"),
    db_allocated_storage=int(_ctx(app, env_cfg, "db_allocated_storage", 20)),
    db_max_allocated_storage=int(_ctx(app, env_cfg, "db_max_allocated_storage", 100)),
    db_backup_days=int(_ctx(app, env_cfg, "db_backup_days", 1)),
    db_engine_version=_ctx(app, env_cfg, "db_engine_version", "15.5"),
    db_publicly_accessible=bool(_ctx(app, env_cfg, "db_publicly_accessible", False)),
    db_deletion_protection=env_cfg.get("db_deletion_protection"),
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
    allow_https=bool(_ctx(app, env_cfg, "allow_https", False)),
    ssh_cidr=_ctx(app, env_cfg, "ssh_cidr", None),
    ssh_key_name=_ctx(app, env_cfg, "ssh_key_name", None),
    db_secret=database.db_instance.secret,
    env=cdk_env,
    stack_name=f"{prefix}-compute",
)

Tags.of(app).add("project", project)
Tags.of(app).add("env", env_name)

app.synth()
