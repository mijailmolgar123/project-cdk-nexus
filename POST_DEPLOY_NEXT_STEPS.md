# Puesta en marcha de la aplicación

Después del despliegue de infraestructura:

- Comprueba la administración de EC2 por SSM y la conectividad privada a PostgreSQL.
- Instala el intérprete y las dependencias fijadas por tu aplicación en un entorno aislado. El bootstrap del stack no sustituye su política de runtime.
- Configura el prefijo SSM que consumirá tu aplicación. Contraseñas, tokens y deploy keys deben ser SecureString o Secrets Manager; no imprimas el archivo de entorno en logs.
- Si restauras datos, valida primero la copia y conserva un respaldo. Ejecuta migraciones únicamente después de revisar el esquema y autorizarlas explícitamente.
- Reinicia el servicio de aplicación y comprueba una lectura SQL, el proxy Nginx y el dominio HTTPS configurado.
- Prueba los horarios de EC2/RDS y las ventanas de backups. Verifica los destinatarios de tus alertas: las alarmas del ejemplo no envían correos por defecto.

Las rutas de la aplicación, servicio, repositorio y dominio se seleccionan mediante configuración privada y variables del workflow. Consulta [README.md](README.md) para el contrato de despliegue y [RDS_BUSINESS_HOURS.md](RDS_BUSINESS_HOURS.md) para los horarios.
