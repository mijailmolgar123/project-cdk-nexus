from typing import Optional

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct


def _render_user_data(
    *,
    app_directory: str,
    app_service_name: str,
    app_env_file_path: str,
    app_port: int,
    bootstrap_packages: list[str],
) -> list[str]:
    package_list = " ".join(bootstrap_packages)

    return [
        "set -euxo pipefail",
        f'BOOTSTRAP_PACKAGES="{package_list}"',
        'if command -v dnf >/dev/null 2>&1; then sudo dnf install -y $BOOTSTRAP_PACKAGES; else sudo yum install -y $BOOTSTRAP_PACKAGES; fi',
        f"sudo mkdir -p {app_directory}",
        f"sudo chown ec2-user:ec2-user {app_directory}",
        f"sudo touch {app_env_file_path}",
        f"sudo chmod 600 {app_env_file_path}",
        f"""sudo tee /etc/systemd/system/{app_service_name}.service >/dev/null <<'EOF'
[Unit]
Description={app_service_name} application service
After=network.target

[Service]
Type=simple
User=ec2-user
Group=ec2-user
WorkingDirectory={app_directory}
EnvironmentFile={app_env_file_path}
ExecStart={app_directory}/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:{app_port} app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF""",
        "sudo rm -f /etc/nginx/conf.d/default.conf",
        f"""sudo tee /etc/nginx/conf.d/{app_service_name}.conf >/dev/null <<'EOF'
server {{
    listen 80;
    server_name _;

    location / {{
        proxy_pass http://127.0.0.1:{app_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }}
}}
EOF""",
        "sudo nginx -t",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable nginx",
        f"sudo systemctl enable {app_service_name}",
        "sudo systemctl restart nginx",
    ]


class ComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        project: str,
        vpc: ec2.IVpc,
        compute_security_group: ec2.ISecurityGroup,
        instance_type: str,
        allow_https: bool,
        ssh_cidr: Optional[str],
        ssh_key_name: Optional[str],
        app_config_parameter_prefix: str,
        app_directory: str,
        app_service_name: str,
        app_env_file_path: str,
        app_port: int,
        bootstrap_packages: list[str],
        app_deploy_key_parameter_name: Optional[str],
        associate_elastic_ip: bool,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"

        compute_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "HTTP",
        )
        if allow_https:
            compute_security_group.add_ingress_rule(
                ec2.Peer.any_ipv4(),
                ec2.Port.tcp(443),
                "HTTPS",
            )
        if ssh_cidr:
            compute_security_group.add_ingress_rule(
                ec2.Peer.ipv4(ssh_cidr),
                ec2.Port.tcp(22),
                "SSH",
            )

        self.security_group = compute_security_group

        instance_family = instance_type.split(".")[0]
        cpu_type = (
            ec2.AmazonLinuxCpuType.ARM_64
            if instance_family.endswith("g")
            else ec2.AmazonLinuxCpuType.X86_64
        )

        instance_kwargs = {}
        if ssh_key_name:
            instance_kwargs["key_name"] = ssh_key_name

        parameter_prefix_arn = self.format_arn(
            service="ssm",
            resource="parameter",
            resource_name=f"{app_config_parameter_prefix.lstrip('/')}/*",
        )

        self.instance = ec2.Instance(
            self,
            "Instance",
            instance_name=f"{prefix}-ec2",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType(instance_type),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(
                cpu_type=cpu_type
            ),
            security_group=self.security_group,
            **instance_kwargs,
        )
        self.instance.user_data.add_commands(
            *_render_user_data(
                app_directory=app_directory,
                app_service_name=app_service_name,
                app_env_file_path=app_env_file_path,
                app_port=app_port,
                bootstrap_packages=bootstrap_packages,
            )
        )
        self.instance.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )
        parameter_resources = [parameter_prefix_arn]
        encryption_context_resources = [parameter_prefix_arn]
        if app_deploy_key_parameter_name:
            deploy_key_parameter_arn = self.format_arn(
                service="ssm",
                resource="parameter",
                resource_name=app_deploy_key_parameter_name.lstrip("/"),
            )
            parameter_resources.append(deploy_key_parameter_arn)
            encryption_context_resources.append(deploy_key_parameter_arn)

        self.instance.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=parameter_resources,
            )
        )
        self.instance.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"ssm.{self.region}.amazonaws.com",
                    },
                    "StringLike": {
                        "kms:EncryptionContext:PARAMETER_ARN": encryption_context_resources,
                    },
                },
            )
        )

        self.elastic_ip = None
        if associate_elastic_ip:
            self.elastic_ip = ec2.CfnEIP(
                self,
                "ElasticIp",
                domain="vpc",
                tags=[
                    {"key": "Name", "value": f"{prefix}-eip"},
                    {"key": "project", "value": project},
                    {"key": "env", "value": env_name},
                ],
            )
            ec2.CfnEIPAssociation(
                self,
                "ElasticIpAssociation",
                allocation_id=self.elastic_ip.attr_allocation_id,
                instance_id=self.instance.instance_id,
            )

        CfnOutput(
            self,
            "InstanceId",
            value=self.instance.instance_id,
        )
        CfnOutput(
            self,
            "PublicIp",
            value=self.instance.instance_public_ip,
        )
        CfnOutput(
            self,
            "PublicDns",
            value=self.instance.instance_public_dns_name,
        )
        if self.elastic_ip is not None:
            CfnOutput(
                self,
                "ElasticIpAddress",
                value=self.elastic_ip.ref,
            )
        CfnOutput(
            self,
            "AppEnvironmentFile",
            value=app_env_file_path,
        )
