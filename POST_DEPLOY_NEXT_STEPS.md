# Pasos Pendientes Después Del Despliegue De Infra

Este documento resume lo que falta después de haber desplegado la infraestructura base en AWS.

## Estado actual

La infraestructura `dev` ya quedó desplegada en la cuenta nueva:

- VPC
- subnets públicas y privadas
- security groups
- EC2
- RDS PostgreSQL
- parámetros SSM de aplicación
- scheduler
- rol OIDC para GitHub Actions

También quedó validado:

- `nginx` está activo en la EC2
- el servicio `myapp` existe, pero todavía no queda operativo hasta instalar la app y cargar configuración
- la deploy key del repo de aplicación ya fue guardada en SSM Parameter Store
- desde la EC2 ya fue posible autenticar y hacer el primer pull del repo

## 1. Verificar o aplicar Elastic IP

La EC2 necesita IP fija si vas a seguir usando despliegue por SSH o si quieres una referencia estable.

Si todavía no está aplicada:

```bash
cd /Users/mijailmolina/dev/segurimax/project-cdk-nexus
source .venv/bin/activate
AWS_PROFILE=cdk-nexus npx cdk deploy segurimax-dev-compute --require-approval never -c env_name=dev
```

Luego verificar el output:

```bash
AWS_PROFILE=cdk-nexus aws cloudformation describe-stacks \
  --stack-name segurimax-dev-compute \
  --query "Stacks[0].Outputs[?OutputKey=='ElasticIpAddress'].OutputValue" \
  --output text \
  --region us-east-1
```

## 2. Preparar la aplicación en la EC2

Entrar por SSM y dejar la app instalada:

```bash
cd /home/ec2-user/app
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn
```

Si el repo ya fue clonado, actualizar con:

```bash
cd /home/ec2-user/app
GIT_SSH_COMMAND='ssh -i /home/ec2-user/.ssh/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes' git pull origin ajustes_bd
```

## 3. Construir `/etc/myapp.env` desde SSM

Crear el archivo de entorno con los parámetros que el stack ya publicó:

```bash
fetch_param() { aws ssm get-parameter --name "$1" --with-decryption --query Parameter.Value --output text; }

sudo tee /etc/myapp.env >/dev/null <<EOF
USE_AWS_SECRET=$(fetch_param /segurimax/dev/app-config/USE_AWS_SECRET)
DB_HOST=$(fetch_param /segurimax/dev/app-config/DB_HOST)
DB_PORT=$(fetch_param /segurimax/dev/app-config/DB_PORT)
DB_NAME=$(fetch_param /segurimax/dev/app-config/DB_NAME)
DB_USER=$(fetch_param /segurimax/dev/app-config/DB_USER)
DB_PASSWORD=$(fetch_param /segurimax/dev/app-config/DB_PASSWORD)
SECRET_KEY=$(fetch_param /segurimax/dev/app-config/SECRET_KEY)
EOF

sudo chmod 600 /etc/myapp.env
```

Validar:

```bash
sudo ls -l /etc/myapp.env
sudo cat /etc/myapp.env
```

## 4. Restaurar la base de datos

Como el cliente PostgreSQL ya quedó instalado en la EC2, restaurar desde esa máquina hacia RDS.

Si el backup fue generado con `pg_dump -Fc`:

```bash
pg_restore \
  --verbose \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  -h <db-host> \
  -U postgres \
  -d proyecto_cotizaciones \
  backup.dump
```

Usar como host el valor de:

- `/segurimax/dev/app-config/DB_HOST`

Antes del restore, si hace falta:

- subir `backup.dump` a la EC2
- exportar `PGPASSWORD`

Ejemplo:

```bash
export PGPASSWORD="$(aws ssm get-parameter --name /segurimax/dev/app-config/DB_PASSWORD --with-decryption --query Parameter.Value --output text)"
```

## 5. Ejecutar migraciones

Después del restore:

```bash
cd /home/ec2-user/app
source venv/bin/activate
venv/bin/flask --app app:create_app db upgrade
```

## 6. Levantar y validar `myapp`

```bash
sudo systemctl restart myapp
sudo systemctl status myapp --no-pager
sudo journalctl -u myapp --no-pager -n 100
```

Validar también:

```bash
curl -I http://127.0.0.1
curl -I http://127.0.0.1:8000
```

## 7. Decidir modo de despliegue continuo

Cuando la app ya esté estable, elegir uno de estos caminos:

- mantener despliegue manual por SSM
- seguir con el workflow actual del repo de app por SSH
- migrar a OIDC + SSM + Parameter Store

## 8. Si luego quieres usar OIDC

Antes de activar despliegue automático con el workflow de este repo:

- corregir `github.owner`
- corregir `github.repo`
- corregir `github.branch`

Esos valores deben apuntar al repo que ejecutará el workflow OIDC, no al repo de aplicación si el workflow corre en `project-cdk-nexus`.
