from typing import Optional

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


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
        db_secret: Optional[secretsmanager.ISecret],
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
        if db_secret:
            db_secret.grant_read(self.instance.role)

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
