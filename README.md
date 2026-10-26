# CDK Nexus

Infraestructura reutilizable para una aplicación Python/Flask en AWS, con AWS CDK v2 y Python. Incluye VPC sin NAT Gateway, EC2 Amazon Linux, PostgreSQL privado en RDS, credenciales generadas, configuración en Parameter Store, acceso por SSM y autenticación OIDC para GitHub Actions.

## Configuración pública y privada

`cdk.json` contiene valores de ejemplo. **No contiene la configuración de una cuenta real.** Copia `cdk.local.example.json` a `cdk.local.json` y completa tus datos. El archivo local se combina con los valores públicos antes de construir los stacks; los diccionarios se combinan recursivamente y las listas se sustituyen completas. `-c env_name=prod` conserva prioridad para elegir el entorno.

```bash
cp cdk.local.example.json cdk.local.json
```

El identificador `111111111111` es ficticio: reemplázalo con tu cuenta. Configura `github.owner`, `github.repo` y `github.branch` con el repositorio **de infraestructura** que ejecutará GitHub Actions. El repositorio de la aplicación se configura por separado mediante `APP_GIT_REPO_SSH_URL`.

`cdk.local.json`, `.private/`, `.env*`, llaves y resultados operativos están ignorados. Conserva en `.private/` endpoints, plantillas obtenidas de AWS, inventarios y reportes de tu organización. Guarda contraseñas y tokens en Secrets Manager o Parameter Store SecureString. Un archivo ya publicado no desaparece del historial por agregarlo a `.gitignore`.

Para seleccionar otro archivo privado usa `CDK_LOCAL_CONFIG=/ruta/al/archivo.json`. Para sintetizar únicamente la configuración pública usa `CDK_LOCAL_CONFIG=''`.

## Preparación local

Usa el Python indicado en `.python-version` y Node.js compatible con tu CDK CLI. Las bibliotecas Python están fijadas en `constraints.txt`; las herramientas están en `requirements-tooling.txt` y el lockfile de Node fija la CLI.

```bash
pyenv install -s "$(cat .python-version)"
python -m venv .venv
make install
make test
make synth ENV_NAME=dev
```

Las herramientas Python se ejecutan con `.venv/bin/python -m ...`. El Python del sistema puede tener una versión diferente.

## Stacks

- `GitHubActionsStack`: proveedor OIDC y rol para el repositorio y rama configurados.
- `NetworkStack`: VPC, subredes públicas/aisladas y grupos de seguridad.
- `DatabaseStack`: PostgreSQL, secreto generado y parámetros de aplicación. Conserva base y credenciales con `Retain`.
- `ComputeStack`: EC2 administrada por SSM, Nginx, servicio systemd y acceso al prefijo SSM de la aplicación.
- `SchedulerStack`: Lambda y horarios independientes para EC2/RDS, reintentos limitados, cola cifrada de fallos y alarmas CloudWatch.
- `UserAdminStack`: opcional con `enable_user_admin=true`. Supone un esquema de usuarios compatible con el Lambda incluido; no es un módulo genérico de autenticación.
- `DatabaseRecoveryStack`: entrada independiente `recovery_app.py` para recuperar a una instancia diferente.

Para adoptar una base existente y retirar la original, `retired_database_template` selecciona una plantilla privada revisada que conserva los IDs de recursos compartidos. No se publica una plantilla correspondiente a una cuenta real. La prueba en `tests/fixtures/` usa datos sintéticos y no sirve para desplegar un entorno real.

## Horarios

Todos los días, por defecto en `America/Lima`:

| Recurso | Inicio | Apagado |
|---|---|---|
| RDS | 07:30 | 21:05 |
| EC2 | 08:00 | 21:00 |

Son configurables con `business_start_hour`, `business_stop_hour`, `rds_start_hour`, `rds_start_minute`, `rds_stop_minute`, `scheduler_manage_rds` y `scheduler_enabled`. EC2 espera a que RDS esté disponible; el apagado de RDS espera a que EC2 esté detenido. Los eventos vencidos no cambian recursos. Las alarmas no incluyen destinatarios: configura tus notificaciones si las necesitas.

Ver [horarios y backups](RDS_BUSINESS_HOURS.md) y [recuperación de RDS](RDS_RECOVERY.md).

## Primer despliegue

Revisa tu configuración local y el diff antes de desplegar. Usa tu perfil AWS; la infraestructura base no instala por sí sola una versión actualizada de todas las dependencias de tu aplicación.

```bash
export AWS_PROFILE=your-profile
./node_modules/.bin/cdk bootstrap aws://YOUR_ACCOUNT_ID/us-east-1
make diff ENV_NAME=dev
make deploy ENV_NAME=dev
```

El despliegue crea recursos facturables. Configura el runtime de tu aplicación de forma aislada; no sustituyas el Python del sistema operativo.

## GitHub Actions

Los pushes y pull requests ejecutan validaciones sin credenciales AWS. **Publicar código no despliega infraestructura.** El workflow `Deploy Infrastructure` se ejecuta manualmente con `workflow_dispatch`.

Para habilitar el despliegue manual configura:

- Variable `AWS_ROLE_ARN`: rol OIDC de tu cuenta.
- Variables `AWS_REGION`, `CDK_ENV_NAME` y las de tu aplicación según el workflow.
- Secreto `CDK_LOCAL_CONFIG_JSON`: contenido de tu configuración privada con un objeto `context`.
- Si usas una plantilla de retiro: secreto opcional `CDK_PRIVATE_TEMPLATES_JSON`, un objeto cuyas claves son nombres de archivos JSON y cuyos valores son las plantillas. El workflow las materializa solo en `.private/templates/`.

No publiques esos valores en archivos de ejemplo. El workflow exige la configuración privada antes de obtener credenciales AWS.

Para desplegar la aplicación por SSM, esta debe proporcionar `deploy/prepare_runtime.sh` y `deploy/load_app_config.py` con el contrato usado en el workflow. Configura `APP_GIT_REPO_SSH_URL`, `APP_GIT_BRANCH`, `APP_HTTP_HOST` y un parámetro SecureString para la deploy key. El flujo instala el entorno fijado por la aplicación; las migraciones solo se ejecutan al seleccionar explícitamente `run_migrations`.

Los valores opcionales `app_config_defaults` inicializan claves faltantes de configuración de la aplicación. No incluyen datos de empresa por defecto; proporciona los tuyos fuera del repositorio. Los tokens existentes se conservan durante cambios de endpoint.

Más detalles: [despliegue en otra cuenta](DEPLOY_NEW_ACCOUNT.md), [puesta en marcha de la aplicación](POST_DEPLOY_NEXT_STEPS.md).

## Revisión antes de publicar

`make test` comprueba la infraestructura y el comportamiento de los Lambdas con dobles locales, sin modificar AWS. El CI comprueba también que no entren configuraciones privadas, datos del operador ni credenciales en el contenido versionado.

La licencia del proyecto está en [LICENSE](LICENSE).
