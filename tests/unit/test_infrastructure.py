import json
import sys
from pathlib import Path

import aws_cdk as cdk
import aws_cdk.assertions as assertions

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from stacks.compute_stack import ComputeStack
from stacks.database_stack import DatabaseStack
from stacks.github_actions_stack import GitHubActionsStack
from stacks.network_stack import NetworkStack
from stacks.scheduler_stack import SchedulerStack


def _build_stacks():
    app = cdk.App()
    env = cdk.Environment(account="111111111111", region="us-east-1")
    app_config_parameter_prefix = "/segurimax/dev/app-config"

    github = GitHubActionsStack(
        app,
        "GitHubActions",
        project="segurimax",
        github_owner="example-org",
        github_repo="example-repo",
        github_branch="main",
        env=env,
    )
    network = NetworkStack(
        app,
        "Network",
        env_name="dev",
        project="segurimax",
        vpc_cidr="10.0.0.0/16",
        public_subnet_cidr_mask=24,
        private_subnet_cidr_mask=24,
        max_azs=1,
        env=env,
    )
    database = DatabaseStack(
        app,
        "Database",
        env_name="dev",
        project="segurimax",
        vpc=network.vpc,
        db_security_group=network.db_security_group,
        db_name="proyecto_cotizaciones",
        db_username="postgres",
        db_instance_class="t4g.micro",
        db_allocated_storage=20,
        db_max_allocated_storage=100,
        db_backup_days=1,
        db_engine_version="17.4",
        app_config_parameter_prefix=app_config_parameter_prefix,
        db_publicly_accessible=False,
        db_deletion_protection=False,
        env=env,
    )
    compute = ComputeStack(
        app,
        "Compute",
        env_name="dev",
        project="segurimax",
        vpc=network.vpc,
        compute_security_group=network.compute_security_group,
        instance_type="t3.micro",
        allow_https=False,
        ssh_cidr="",
        ssh_key_name="",
        app_config_parameter_prefix=app_config_parameter_prefix,
        app_directory="/home/ec2-user/app",
        app_service_name="myapp",
        app_env_file_path="/etc/myapp.env",
        app_port=8000,
        bootstrap_packages=[
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
        app_deploy_key_parameter_name="/your-app/dev/github/deploy-key",
        associate_elastic_ip=True,
        env=env,
    )
    scheduler = SchedulerStack(
        app,
        "Scheduler",
        env_name="dev",
        project="segurimax",
        ec2_instance=compute.instance,
        database_instance=database.db_instance,
        schedule_timezone="America/Lima",
        business_start_hour=8,
        business_stop_hour=21,
        scheduler_enabled=True,
        env=env,
    )

    return github, database, compute, scheduler


def test_database_stack_creates_expected_app_config_parameters():
    _, database, _, _ = _build_stacks()
    template = assertions.Template.from_stack(database)

    template.resource_count_is("AWS::SSM::Parameter", 5)
    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/segurimax/dev/app-config/DB_HOST",
            "Tier": "Standard",
            "Type": "String",
        },
    )
    template.has_resource_properties(
        "AWS::CloudFormation::CustomResource",
        {
            "DbPasswordParameterName": "/segurimax/dev/app-config/DB_PASSWORD",
            "SecretKeyParameterName": "/segurimax/dev/app-config/SECRET_KEY",
        },
    )


def test_compute_role_can_read_only_expected_parameter_paths():
    _, _, compute, _ = _build_stacks()
    template = assertions.Template.from_stack(compute)

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": assertions.Match.array_with(
                    [
                        assertions.Match.object_like(
                            {
                                "Action": ["ssm:GetParameter", "ssm:GetParameters"],
                                "Resource": assertions.Match.array_with(
                                    [
                                        assertions.Match.object_like(
                                            {
                                                "Fn::Join": assertions.Match.any_value()
                                            }
                                        )
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_compute_user_data_bootstraps_nginx_and_systemd():
    _, _, compute, _ = _build_stacks()
    template = assertions.Template.from_stack(compute)
    resources = template.find_resources("AWS::EC2::Instance")

    assert resources
    serialized = json.dumps(next(iter(resources.values())))
    assert "nginx" in serialized
    assert "myapp.service" in serialized
    assert "/etc/myapp.env" in serialized
    assert "proxy_pass http://127.0.0.1:8000" in serialized


def test_compute_stack_associates_elastic_ip_when_enabled():
    _, _, compute, _ = _build_stacks()
    template = assertions.Template.from_stack(compute)

    template.resource_count_is("AWS::EC2::EIP", 1)
    template.resource_count_is("AWS::EC2::EIPAssociation", 1)


def test_scheduler_stack_creates_start_and_stop_schedules():
    _, _, _, scheduler = _build_stacks()
    template = assertions.Template.from_stack(scheduler)

    template.resource_count_is("AWS::Scheduler::Schedule", 2)
    template.has_resource_properties(
        "AWS::Scheduler::Schedule",
        {
            "ScheduleExpressionTimezone": "America/Lima",
        },
    )


def test_github_role_is_limited_to_repo_and_branch_and_can_start_infra():
    github, _, _, _ = _build_stacks()
    template = assertions.Template.from_stack(github)
    policies = template.find_resources("AWS::IAM::Policy")

    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": assertions.Match.array_with(
                    [
                        assertions.Match.object_like(
                            {
                                "Condition": {
                                    "StringEquals": {
                                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                        "token.actions.githubusercontent.com:sub": "repo:example-org/example-repo:ref:refs/heads/main",
                                    }
                                }
                            }
                        )
                    ]
                )
            }
        },
    )
    assert any("rds:StartDBInstance" in json.dumps(policy) for policy in policies.values())
    assert any("ec2:StartInstances" in json.dumps(policy) for policy in policies.values())
