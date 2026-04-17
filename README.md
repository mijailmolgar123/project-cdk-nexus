# CDK Nexus

Infraestructura base para un ERP desplegado en AWS con AWS CDK v2 y Python.
El repo crea la red, la EC2, la base PostgreSQL, el rol OIDC para GitHub Actions y el scheduler que prende y apaga EC2 y RDS en horario laboral.

## Arquitectura

- `GitHubActionsStack`
  - Proveedor OIDC de GitHub.
  - Rol IAM para GitHub Actions sin access keys fijas.
  - Permisos para asumir roles de bootstrap de CDK y disparar despliegues por SSM.

- `NetworkStack`
  - VPC sin NAT Gateway.
  - Subred publica para EC2 y privada aislada para RDS.
  - Security groups para HTTP/HTTPS y acceso de EC2 hacia PostgreSQL.

- `DatabaseStack`
  - RDS PostgreSQL con credenciales generadas en Secrets Manager.
  - Replica `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `SECRET_KEY` y `USE_AWS_SECRET=false` a `SSM Parameter Store`.
  - Proteccion de borrado configurable por ambiente.

- `ComputeStack`
  - EC2 Amazon Linux 2023.
  - Bootstrap por `user_data` para `nginx`, `systemd`, `python3.11` y dependencias de `WeasyPrint`.
  - `nginx` en `:80`, `gunicorn` en `127.0.0.1:8000` y `EnvironmentFile` en `/etc/myapp.env`.
  - Acceso de solo lectura al prefijo de parámetros SSM de la app.
  - `AmazonSSMManagedInstanceCore` para administrar y desplegar sin SSH.

- `SchedulerStack`
  - Lambda de operacion.
  - Dos schedules de EventBridge Scheduler en `America/Lima`.
  - Inicio `08:00` y apagado `21:00` para EC2 y RDS.

## Lo que resuelve

- Sin llaves AWS de larga duracion en GitHub.
- Sin necesidad de abrir SSH para despliegues automatizados.
- Horario operativo configurable por ambiente.
- Configuracion sin datos personales en el repositorio.
- Primer bootstrap de EC2 casi listo desde el stack, sin configurar `nginx` manualmente.

## Requisitos

- Python 3.10+
- Python y Node instalados localmente, por ejemplo con Homebrew
- Node.js 20+ para la CLI local de CDK
- AWS CDK v2
- Una cuenta AWS con permisos de bootstrap y despliegue inicial

## Flujo local aislado

Este repo esta preparado para un flujo por proyecto:

- Usa la version de Python instalada en tu máquina, por ejemplo con `brew install python@3.11`.
- `.venv` guarda dependencias Python locales al repo.
- `node_modules/.bin/cdk` provee la CLI de CDK sin instalarla globalmente.

Ejemplo de setup:

```bash
brew install python@3.11 node@20
python3.11 -m venv .venv
source .venv/bin/activate
make install
```

Si Homebrew instala `node@20` fuera del `PATH` por defecto, exporta su binario antes de correr `make install`. El repo no depende de paquetes Python ni Node globales fuera de esas herramientas base.

## Contexto

La configuracion vive en `cdk.json`.

- `github.owner`, `github.repo`, `github.branch`: repo autorizado a asumir el rol OIDC.
- `environments.<env>.region`: región objetivo del ambiente.
- `environments.<env>.schedule_timezone`: zona horaria del scheduler.
- `environments.<env>.business_start_hour`: hora de encendido.
- `environments.<env>.business_stop_hour`: hora de apagado.
- `environments.<env>.app_deploy_key_parameter_name`: nombre del `SecureString` en Parameter Store que guarda la deploy key de GitHub.
- `environments.<env>.app_config_parameter_prefix`: prefijo SSM donde la app leerá `DB_*`, `SECRET_KEY` y `USE_AWS_SECRET`.
- `environments.<env>.app_directory`, `app_service_name`, `app_env_file_path`, `app_port`: contrato de runtime en EC2.
- `ssh_cidr` y `ssh_key_name`: opcionales. El flujo recomendado usa SSM y no requiere SSH.

## Primer despliegue

El rol OIDC no existe hasta que lo creas por primera vez. Por eso el primer despliegue se hace con credenciales locales:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
npx cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
make deploy ENV_NAME=dev
```

Ese despliegue crea:

- `segurimax-github-actions`
- `segurimax-dev-network`
- `segurimax-dev-database`
- `segurimax-dev-compute`
- `segurimax-dev-scheduler`

## GitHub Actions

El workflow vive en `.github/workflows/deploy.yml`.

Variables de GitHub recomendadas:

- `AWS_ROLE_ARN`: output `GitHubActionsRoleArn` del stack `segurimax-github-actions`
- `AWS_REGION`: region de despliegue
- `CDK_ENV_NAME`: ambiente por defecto, por ejemplo `dev`
- `PROJECT_NAME`: normalmente `segurimax`
- `APP_GIT_REPO_SSH_URL`: repositorio Git por SSH, por ejemplo `git@github.com:tu-org/tu-repo.git`
- `APP_GIT_BRANCH`: rama a desplegar, por ejemplo `ajustes_bd`
- `APP_DIRECTORY`: ruta de la app en la EC2, por ejemplo `/home/ec2-user/app`
- `APP_SERVICE_NAME`: servicio systemd a reiniciar, por ejemplo `myapp`
- `APP_FLASK_APP`: valor para Flask CLI, por ejemplo `app:create_app`
- `APP_ENV_FILE_PATH`: ruta del archivo de entorno que consumirá `systemd`, por ejemplo `/etc/myapp.env`
- `APP_CONFIG_PARAMETER_PREFIX`: prefijo SSM con la configuración de la app
- `APP_DEPLOY_KEY_PARAMETER_NAME`: nombre del `SecureString` con la deploy key
- `APP_SYSTEM_PACKAGES`: paquetes RPM opcionales para instalar antes del deploy

## Despliegue barato con Parameter Store

Para gastar lo menos posible:

- usa `SSM Parameter Store` para configuración y deploy key
- deja `DB_PASSWORD`, `SECRET_KEY` y la deploy key como `SecureString`
- mantente en `Standard` para evitar cargos del tier `Advanced`
- usa la llave administrada por AWS `aws/ssm` y no una KMS propia

Los `Standard SecureString` tienen limite de 4 KB, suficiente para una deploy key normal. AWS documenta que los parametros avanzados generan cargos y que `SecureString` usa KMS para cifrado. Fuentes:

- https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html
- https://docs.aws.amazon.com/systems-manager/latest/userguide/secure-string-parameter-kms-encryption.html

Crear el parametro:

```bash
aws ssm put-parameter \
  --name "/your-app/dev/github/deploy-key" \
  --type "SecureString" \
  --tier "Standard" \
  --value "$(cat deploy_key.pem)" \
  --overwrite
```

Con esa configuracion no necesitas entrar manualmente a la EC2 para copiar la key. El workflow la recupera durante el deploy por SSM, directamente desde Parameter Store.

La configuración de aplicación también sale de `SSM Parameter Store`. El stack publica:

- `USE_AWS_SECRET=false`
- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `SECRET_KEY`

Durante cada deploy, GitHub Actions reconstruye `/etc/myapp.env` con esos parámetros antes de correr migraciones y reiniciar `myapp`.

Secret opcional para despliegue de aplicacion por SSM:

- `ERP_DEPLOY_COMMANDS_B64`: comandos shell codificados en base64, una linea por comando

Ejemplo alineado con un despliegue tipo Flask en EC2:

```bash
cat <<'EOF' | base64
cd /home/ec2-user/app
source venv/bin/activate
venv/bin/pip install -r requirements.txt
venv/bin/flask --app app:create_app db upgrade
sudo systemctl restart myapp
EOF
```

Si defines `APP_DEPLOY_KEY_PARAMETER_NAME` y `APP_GIT_REPO_SSH_URL`, el workflow usa el flujo automatico por Parameter Store. Si no, todavia puedes usar `ERP_DEPLOY_COMMANDS_B64` como fallback manual.

El workflow ya contempla el primer deploy: enciende EC2 y RDS si el scheduler las dejó apagadas, espera a que SSM esté `Online`, clona el repo si todavía no existe, crea `venv` si falta, instala `gunicorn`, corre `db upgrade`, reinicia `myapp` y valida tanto `gunicorn` como `nginx`.

## Operacion diaria

- EC2 y RDS arrancan a las `08:00` y se apagan a las `21:00`.
- La evaluacion del horario se hace en `America/Lima`.
- RDS puede detenerse de forma diaria sin problema; AWS solo fuerza arranque si pasan 7 dias continuos detenida.
- Si un deploy cae fuera de horario, el workflow vuelve a encender EC2 y RDS antes de desplegar.

## Validacion local

```bash
make synth ENV_NAME=dev
make test
```

## Runbook

Para el paso a paso operativo completo de migracion a una cuenta nueva, restore de RDS y fallback de upgrade, revisa [DEPLOY_NEW_ACCOUNT.md](/Users/mijailmolina/dev/segurimax/project-cdk-nexus/DEPLOY_NEW_ACCOUNT.md:1).
