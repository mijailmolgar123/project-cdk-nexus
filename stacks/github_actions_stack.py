from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct


class GitHubActionsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: str,
        github_owner: str,
        github_repo: str,
        github_branch: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOidcProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        role = iam.Role(
            self,
            "GitHubActionsRole",
            role_name=f"{project}-github-actions-role",
            description="Assumed by GitHub Actions through OIDC for CDK deployments and SSM app rollout.",
            assumed_by=iam.OpenIdConnectPrincipal(
                provider,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_owner}/{github_repo}:ref:refs/heads/{github_branch}"
                        ),
                    }
                },
            ),
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRoles",
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:{self.partition}:iam::{self.account}:role/cdk-*",
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadBootstrapMetadata",
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:GetTemplate",
                    "cloudformation:ListStackResources",
                    "ssm:GetParameter",
                    "ssm:DescribeInstanceInformation",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ManageInfrastructurePowerState",
                actions=[
                    "ec2:DescribeInstances",
                    "ec2:StartInstances",
                    "rds:DescribeDBInstances",
                    "rds:StartDBInstance",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="DeployApplicationWithSsm",
                actions=[
                    "ssm:SendCommand",
                    "ssm:GetCommandInvocation",
                    "ssm:ListCommandInvocations",
                    "ssm:CancelCommand",
                ],
                resources=["*"],
            )
        )

        self.role = role

        CfnOutput(
            self,
            "GitHubActionsRoleArn",
            value=role.role_arn,
        )
        CfnOutput(
            self,
            "GitHubActionsRoleName",
            value=role.role_name,
        )
