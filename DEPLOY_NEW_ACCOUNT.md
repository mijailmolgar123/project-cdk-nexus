# Runbook Operativo: Despliegue En Cuenta Nueva

Este documento describe el paso a paso operativo para mover esta base de infraestructura a una cuenta AWS nueva, conectar GitHub Actions, restaurar la base de datos antigua y dejar un fallback razonable para upgrade de PostgreSQL con el menor costo operativo posible.

El objetivo es:

- usar `GitHub Actions` con `OIDC`
- evitar `SSH` desde GitHub Actions
- guardar la deploy key en `SSM Parameter Store`
- restaurar la RDS antigua sin romper compatibilidad
- no crear más recursos de los necesarios

## 1. Decisiones base

Antes de tocar la cuenta nueva, fija estas decisiones:

- Python local del repo: `3.11.x` instalado con Homebrew
- despliegue local: `Homebrew` + `.venv`
- CDK local: `node_modules/.bin/cdk`
- autenticación de CI/CD: `OIDC`
- deploy de aplicación: `SSM Run Command`
- credencial de `git pull` dentro de EC2: `SSM Parameter Store SecureString Standard`

## 2. Checklist de información que debes tener

Reúne esto antes de desplegar:

- `AWS Account ID` de la cuenta nueva
- región objetivo, por ejemplo `us-east-2`
- nombre del repo GitHub
- branch a desplegar, por ejemplo `ajustes_bd`
- ruta de la app en la EC2, por ejemplo `/home/ec2-user/app`
- nombre del servicio systemd, por ejemplo `myapp`
- valor Flask CLI, por ejemplo `app:create_app`
- nombre deseado del parámetro SSM para la deploy key
- snapshot o backup de la RDS antigua
- versión de PostgreSQL usada por la RDS antigua
- extensiones PostgreSQL usadas por la app

## 3. Verificar la RDS antigua antes de restaurar

No restaures a ciegas una RDS nueva con otra major version si no sabes qué usaba la base anterior.

### 3.1 Información mínima que debes sacar

Si todavía tienes acceso a la base anterior, ejecuta:

```sql
SHOW server_version;
SELECT version();
SELECT extname, extversion FROM pg_extension ORDER BY extname;
SHOW max_connections;
SHOW shared_preload_libraries;
```

También revisa:

- `DB parameter group`
- `DB option group` si aplica
- tamaño de almacenamiento usado
- si tiene `automated backups` o solo snapshot manual

### 3.2 Si no tienes acceso SQL pero sí acceso AWS

En la consola o por CLI revisa:

```bash
aws rds describe-db-instances --db-instance-identifier <db-id>
aws rds describe-db-snapshots --db-instance-identifier <db-id>
```

Busca especialmente:

- `EngineVersion`
- clase de instancia
- subnet group
- parameter group

## 4. Regla segura para el restore

La estrategia de menor riesgo es:

1. restaurar primero con la misma major version del origen
2. probar la aplicación
3. recién después decidir si haces upgrade

Ejemplo:

- si la base vieja era PostgreSQL 13.x, restaura primero en PostgreSQL 13
- no saltes directo a PostgreSQL 15.5 solo porque el stack hoy lo tiene por default

## 5. Setup local del repo

En tu máquina:

```bash
brew install python@3.11 node@20
python3.11 -m venv .venv
source .venv/bin/activate
make install
```

Verifica:

```bash
python --version
node --version
./node_modules/.bin/cdk --version
```

Resultado esperado:

- Python `3.11.x`
- Node `20+`
- CDK CLI disponible localmente

## 6. Configurar `cdk.json`

Ajusta estos campos por ambiente:

- `github.owner`
- `github.repo`
- `github.branch`
- `environments.<env>.account`
- `environments.<env>.region`
- `environments.<env>.app_deploy_key_parameter_name`
- `environments.<env>.db_engine_version`

Recomendación:

- `dev` y `prod` deben tener parámetros SSM distintos
- usa nombres explícitos, por ejemplo:
  - `/segurimax/dev/github/deploy-key`
  - `/segurimax/prod/github/deploy-key`

## 7. Crear la deploy key en GitHub

Genera una key solo de lectura para el repo de la aplicación:

```bash
ssh-keygen -t ed25519 -C "segurimax-deploy" -f deploy_key
```

Usa:

- `deploy_key.pub` como Deploy Key en GitHub
- `deploy_key` como valor secreto en AWS

## 8. Guardar la key en Parameter Store con el menor costo

Usa `SecureString` y `Standard`, no `Advanced`.

```bash
aws ssm put-parameter \
  --name "/segurimax/dev/github/deploy-key" \
  --type "SecureString" \
  --tier "Standard" \
  --value "$(cat deploy_key)" \
  --overwrite
```

Recomendación de costo:

- mantente en `Standard`
- usa la key administrada `aws/ssm`
- no crees una KMS customer-managed key salvo que tengas un requisito real

## 9. Configurar GitHub Actions

En GitHub, define estas Variables:

- `AWS_ROLE_ARN`
- `AWS_REGION`
- `CDK_ENV_NAME`
- `PROJECT_NAME`
- `APP_GIT_REPO_SSH_URL`
- `APP_GIT_BRANCH`
- `APP_DIRECTORY`
- `APP_SERVICE_NAME`
- `APP_FLASK_APP`
- `APP_SYSTEM_PACKAGES`

Valores alineados con tu caso actual:

- `APP_GIT_BRANCH=ajustes_bd`
- `APP_DIRECTORY=/home/ec2-user/app`
- `APP_SERVICE_NAME=myapp`
- `APP_FLASK_APP=app:create_app`
- `APP_SYSTEM_PACKAGES=pango gdk-pixbuf2 cairo fontconfig libffi`

No necesitas guardar `EC2_HOST`, `EC2_SSH_KEY` ni llaves AWS largas en GitHub.

## 10. Primer despliegue en la cuenta nueva

El primer despliegue crea el rol OIDC, así que debe hacerse desde tu máquina con credenciales AWS válidas.

```bash
export AWS_PROFILE=<tu-profile>
npx cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
make deploy ENV_NAME=dev
```

Esto crea:

- stack de GitHub Actions OIDC
- red
- EC2
- RDS
- scheduler

## 11. Verificación inicial dentro de la EC2

Este repo ahora deja la instancia base lista por `user_data`:

- instala `nginx`, `git`, `python3.11` y librerías del runtime
- registra `myapp.service`
- deja `nginx` escuchando en `80` y proxy a `127.0.0.1:8000`
- crea `/home/ec2-user/app` y `/etc/myapp.env`

Entrar por `SSM Session Manager` queda como verificación opcional, no como bootstrap obligatorio.

### 11.1 Verificaciones iniciales

Dentro de la EC2:

```bash
whoami
python3 --version
python3.11 --version
git --version
systemctl status amazon-ssm-agent --no-pager
systemctl status nginx --no-pager
systemctl status myapp --no-pager
```

Si la instancia es nueva y el `user_data` terminó bien, no deberías tener que instalar paquetes a mano. Solo valida que el servicio exista:

```bash
systemctl cat myapp
cat /etc/nginx/conf.d/myapp.conf
```

## 12. Restore de la RDS antigua en la cuenta nueva

### 12.1 Estrategia de menor riesgo

1. comparte o copia el snapshot a la cuenta nueva
2. restaura una RDS temporal con la misma major version
3. valida la app
4. recién después decides upgrade o cutover final

### 12.2 Estrategia de menor costo

Para pruebas:

- usa una sola instancia `Single-AZ`
- usa una clase pequeña compatible
- no crees una segunda RDS final hasta validar

Haz el restore temporal y prueba ahí primero.

## 13. Verificación post-restore

Antes de conectar la app:

```sql
SHOW server_version;
SELECT current_database();
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

Verifica también:

- que el endpoint responde
- que los parámetros `DB_*` y `SECRET_KEY` existen en `SSM Parameter Store`
- que la EC2 alcanza la RDS por red

Desde EC2:

```bash
aws ssm get-parameters --with-decryption --names \
  /segurimax/dev/app-config/DB_HOST \
  /segurimax/dev/app-config/DB_PORT \
  /segurimax/dev/app-config/DB_NAME \
  /segurimax/dev/app-config/DB_USER \
  /segurimax/dev/app-config/DB_PASSWORD \
  /segurimax/dev/app-config/SECRET_KEY
```

Si tienes `psql` disponible:

```bash
psql "host=<endpoint> dbname=<db> user=<user> sslmode=require"
```

## 14. Fallback para upgrade de PostgreSQL sin romper nada

Si descubres que la base antigua usa una versión vieja y quieres subirla después, el camino más seguro y barato es este:

1. restaura snapshot en la misma major version
2. valida que la aplicación funciona
3. toma un snapshot manual de esa RDS ya validada
4. intenta el major upgrade sobre esa RDS temporal o sobre una copia
5. vuelve a probar la app
6. si algo falla, vuelves al snapshot validado

No cambies al mismo tiempo:

- cuenta AWS
- infraestructura
- versión de PostgreSQL
- versión de Python de la app

Haz esos cambios por etapas.

## 15. Orden recomendado de ejecución

Orden operativo sugerido:

1. verificar versión PostgreSQL y extensiones de la base vieja
2. configurar `cdk.json`
3. crear parámetro SSM con la deploy key
4. bootstrap y deploy inicial en la cuenta nueva
5. bootstrap mínimo manual de EC2 por Session Manager
6. restaurar RDS temporal con misma major version
7. conectar la app y probar
8. ejecutar GitHub Actions hacia `dev`
9. decidir si haces upgrade de PostgreSQL
10. recién después formalizar `prod`

## 16. Qué NO hacer

Evita esto:

- restaurar la base vieja directamente sobre PostgreSQL 15 sin validar compatibilidad
- crear una KMS propia si solo buscas guardar una deploy key barata
- abrir SSH solo para automatizar deploys
- mezclar `dev` y `prod` con el mismo parámetro SSM
- depender de una instalación global de Python o CDK en tu laptop

## 17. Checklist final de validación

Infra:

- `make synth ENV_NAME=dev`
- `make deploy ENV_NAME=dev`
- EC2 visible y administrada por SSM
- RDS creada o restaurada correctamente
- scheduler visible en EventBridge Scheduler

App:

- `git pull` funciona desde la EC2 usando la key de Parameter Store
- `venv/bin/pip install -r requirements.txt` funciona
- `venv/bin/flask --app app:create_app db upgrade` funciona
- `sudo systemctl restart myapp` funciona
- la app responde por HTTP/HTTPS según tu setup

Base de datos:

- versión PostgreSQL verificada
- extensiones verificadas
- snapshot manual tomado antes de cualquier major upgrade

## 18. Criterio práctico para tu caso

Si quieres el menor costo y la menor complejidad:

- usa una sola EC2
- usa una sola RDS restaurada primero en la misma major version antigua
- no hagas major upgrade el mismo día del cambio de cuenta
- usa `Parameter Store SecureString Standard`
- usa `OIDC` para GitHub Actions
- usa `SSM` para deploy

Ese camino no es el más sofisticado, pero sí es el más controlable y barato para mover tu ERP sin multiplicar riesgos.
