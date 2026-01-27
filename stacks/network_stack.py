from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        project: str,
        vpc_cidr: str,
        public_subnet_cidr_mask: int,
        private_subnet_cidr_mask: int,
        max_azs: int,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = f"{project}-{env_name}"

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name=f"{prefix}-vpc",
            ip_addresses=ec2.IpAddresses.cidr(vpc_cidr),
            max_azs=max_azs,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=public_subnet_cidr_mask,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=private_subnet_cidr_mask,
                ),
            ],
        )

        self.compute_security_group = ec2.SecurityGroup(
            self,
            "ComputeSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"{prefix}-ec2-sg",
            allow_all_outbound=True,
        )
        self.db_security_group = ec2.SecurityGroup(
            self,
            "DbSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"{prefix}-db-sg",
        )
        self.db_security_group.add_ingress_rule(
            peer=self.compute_security_group,
            connection=ec2.Port.tcp(5432),
            description="EC2 to RDS",
        )
