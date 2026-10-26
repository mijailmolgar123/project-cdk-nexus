# Desplegar en una cuenta propia

1. Prepara el Python de `.python-version`, la CLI local y las dependencias con `make install`.
2. Copia `cdk.local.example.json` a `cdk.local.json`; configura cuenta, región, proyecto y el repositorio de infraestructura autorizado por OIDC.
3. Selecciona el perfil AWS con `AWS_PROFILE`. Bootstrap requiere credenciales locales porque el rol OIDC todavía no existe.
4. Ejecuta `make synth`, `make diff` y después el despliegue revisado. Los stacks crean recursos facturables.
5. Comprueba que EC2 aparece administrada por SSM, RDS es privada y las credenciales están en Secrets Manager/Parameter Store.
6. Configura el repositorio de aplicación, su deploy key de solo lectura en SecureString y los scripts de runtime que espera el workflow.
7. Para restaurar datos existentes sigue [RDS_RECOVERY.md](RDS_RECOVERY.md); valida la copia antes de cambiar la conexión. Revisa aparte cualquier cambio de versión mayor de PostgreSQL.
8. Configura `AWS_ROLE_ARN` y los secretos privados del workflow si deseas usar el despliegue manual de GitHub Actions. No hay despliegues automáticos por push.
9. Prueba SQL, HTTP/HTTPS y un ciclo de horarios; alinea backups y mantenimiento con las horas de encendido.

Los datos específicos de cada cuenta y sus informes operativos pertenecen a `.private/` y `cdk.local.json`. Mantén los parámetros de desarrollo y producción separados. La configuración pública usa ejemplos, no identifica una instalación existente.
