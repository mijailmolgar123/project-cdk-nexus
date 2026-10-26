# Recuperación de PostgreSQL en otra instancia

`recovery_app.py` usa un stack independiente y una instancia con identificador diferente del origen. La base original, la recuperada y las credenciales se conservan con `Retain`. El stack exige un momento de restauración explícito y un ID inmutable de origen; no modifica el esquema de la aplicación.

En `cdk.local.json`, agrega `context.environments.dev.database_recovery` con:

- `account`, `source_instance_identifier`, `source_resource_id`.
- `target_instance_identifier` con el prefijo de tu proyecto y entorno.
- `restore_time` en UTC y con zona horaria.
- `db_subnet_group_name`, `db_security_group_ids` y `availability_zone` existentes.
- Opcionalmente clase, retención y ventanas de backup/mantenimiento.

Estos valores deben permanecer fuera del repositorio. Revisa la plantilla y el diff usando la entrada independiente:

```bash
./node_modules/.bin/cdk synth --app '.venv/bin/python recovery_app.py' -c env_name=dev
./node_modules/.bin/cdk diff --app '.venv/bin/python recovery_app.py' -c env_name=dev
```

Despliega solo el stack de recuperación revisado. Valida la copia antes de cambiar `active_db_host` y `active_db_instance_identifier`. Los dos campos se configuran juntos; `scheduler_manage_rds=false` permite excluir temporalmente la base de los apagados durante la transición.

`validate_rds_recovery.py` hace comprobaciones SQL de solo lectura desde un host con acceso a la red privada. Requiere dependencias de cliente PostgreSQL y SQLAlchemy en ese host. Recibe `--host`, `--secret-id`, `--region` y opcionalmente `--app-path`; las credenciales se obtienen en memoria de Secrets Manager. Guarda su salida en `.private/` porque puede contener metadatos y cantidades de registros de tu aplicación.

Después del corte, verifica conexiones, lectura SQL y HTTPS. Una instancia nueva y la original no se mantienen sincronizadas automáticamente. No vuelvas a la original sin evaluar los datos escritos después del corte. Si el origen fue eliminado y su backup PITR expiró, una recuperación posterior debe partir de un snapshot conservado mediante un procedimiento nuevo, no reutilizar el ID de origen antiguo.

Para reactivar horarios o retirar la anterior, consulta [RDS_BUSINESS_HOURS.md](RDS_BUSINESS_HOURS.md).
