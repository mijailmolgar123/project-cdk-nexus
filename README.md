# CDK Nexus (AWS CDK v2 - Python)

Infraestructura para una app web existente que se despliega por GitHub Actions a una EC2.
Este repo SOLO crea infraestructura (sin app ni Nginx), free-tier friendly y replicable.

## Resumen de arquitectura

- NetworkStack
  - VPC con CIDR configurable
  - Subnets publicas + privadas aisladas (sin NAT Gateway)
  - Security Groups:
    - EC2 SG: HTTP 80 abierto, HTTPS 443 opcional, SSH 22 solo desde `ssh_cidr`
    - RDS SG: solo 5432 desde el SG de la EC2

- DatabaseStack
  - RDS PostgreSQL (clase configurable, por defecto free-tier friendly `t4g.micro`)
  - Credenciales generadas en AWS Secrets Manager
  - Endpoint y nombre del secreto como outputs

- ComputeStack
  - EC2 t3.micro/t2.micro (configurable) en subnets publicas
  - Rol IAM para leer el secreto de RDS (por defecto)
  - Outputs: InstanceId, PublicIp, PublicDns

## Principios clave

- No hay NAT Gateway (costo) -> EC2 en subnets publicas.
- RDS en subnets privadas aisladas (no public).
- Secretos NO hardcodeados: credenciales en Secrets Manager.
- Tags: `project` y `env`.
- Nombres con prefijo `project-env` para idempotencia y claridad.
- Soporte multi-entorno via `context` (`env_name`).
- Single-AZ por defecto (`max_azs: 1`).

## Requisitos

- Python 3.10+ recomendado
- AWS CDK v2 (CLI instalado)
- Credenciales AWS validas (AWS_PROFILE o variables)

## Configuracion por contexto (cdk.json)

Los valores se leen desde `cdk.json` (o `-c` por CLI). Ejemplo relevante:

```
"context": {
  "project": "segurimax",
  "env_name": "dev",
  "environments": {
    "dev": {
      "account": "123456789012",
      "region": "us-east-2",
      "vpc_cidr": "10.0.0.0/16",
      "max_azs": 1,
      "instance_type": "t3.micro",
      "allow_https": false,
      "ssh_cidr": "203.0.113.10/32",
      "ssh_key_name": "mi-keypair",
      "db_name": "appdb",
      "db_username": "appuser",
      "db_instance_class": "t4g.micro"
    }
  }
}
```

Notas:
- `ssh_key_name` es el nombre del Key Pair existente en EC2. Si esta vacio, no se asigna key.
- `ssh_cidr` debe ser tu IP publica en formato CIDR.
- `account` y `region` pueden venir del perfil AWS si no se setean aqui.

## Flujo recomendado (desde cero)

1) Crear entorno virtual e instalar dependencias
```
python -m venv .venv
pip install -r requirements.txt
```

2) Configurar contexto en `cdk.json` (o por CLI)

3) (Opcional pero recomendado) Bootstrap de CDK en la cuenta/region
```
cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
```

4) Synth/diff/deploy
```
cdk synth -c env_name=dev
cdk diff -c env_name=dev
cdk deploy -c env_name=dev
```

## SSH a la EC2

Para poder entrar por SSH:
- Crea un Key Pair en EC2 y descarga el `.pem`.
- Pon el nombre en `ssh_key_name`.
- Asegura que `ssh_cidr` incluya tu IP publica.

Ejemplo de conexion:
```
ssh -i mi-keypair.pem ec2-user@<PublicIp>
```

## Secreto de RDS (Secrets Manager)

El secreto se genera automaticamente con:
- `username` (definido en context)
- `password` generado

La EC2 tiene permisos IAM para leerlo. Ejemplo desde la instancia:
```
aws secretsmanager get-secret-value --secret-id <project-env>/rds/<db_name>
```

## Notas sobre CDK CLI

- `cdk diff` compara lo desplegado vs lo que se va a desplegar.
- El aviso de "lookup-role" indica que no pudo asumir el rol de bootstrap; si falla en deploy, ejecuta `cdk bootstrap`.
- El mensaje de "feature flags" y telemetria es informativo. Se puede ocultar con:
  - `cdk flags --unstable=flags`
  - `cdk acknowledge 34892`

## Ajustes comunes

- Single-AZ: `max_azs: 1` (por defecto en dev/prod).
- HTTPS: `allow_https: true`.
- RDS retention: `db_deletion_protection: true` en prod.
- RDS clase: `db_instance_class` (free-tier friendly recomendado: `t4g.micro`).

## Estructura del proyecto

```
app.py
cdk.json
requirements.txt
stacks/
  network_stack.py
  database_stack.py
  compute_stack.py
```
