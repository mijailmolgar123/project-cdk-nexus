# Horarios de EC2 y RDS

La política pública separa los horarios: RDS 07:30–21:05 y EC2 08:00–21:00, todos los días en America/Lima. Cada entorno puede cambiar estos valores en su configuración privada.

El Lambda acepta `resource=ec2` o `resource=rds`. Antes de arrancar EC2 comprueba que la base esté disponible; antes de detener RDS comprueba que EC2 esté detenido. Scheduler y Lambda limitan los eventos a cinco minutos para evitar reintentos fuera de horario. Los fallos se conservan en una cola SQS cifrada durante 14 días y hay alarmas CloudWatch, sin destinatarios preconfigurados.

Para la entrada de recuperación, las ventanas de ejemplo son backup diario `13:30-14:00` UTC y mantenimiento `sun:14:30-sun:15:00` UTC: 08:30 y domingos 09:30 respectivamente en Lima. Ajusta ambas si cambias zona u horas de encendido. Mantén la retención de backups apropiada para tus datos; los snapshots conservados siguen ocupando almacenamiento.

Antes de habilitar apagados, respalda y prueba un ciclo controlado de arranque con comprobaciones SQL y HTTPS. El arranque requiere capacidad disponible y puede tardar; el margen entre RDS y EC2 debe basarse en mediciones de tu entorno.

Para retirar una base anterior, revisa las referencias y consumidores, conserva un snapshot verificado y separa el retiro de la eliminación física. El modo `retired_database_template` evita recrear la base antigua y conserva los recursos compartidos mediante una plantilla privada del entorno. `deploy/stack-policies/recovery-protect.json` muestra una política que impide reemplazar o eliminar la base activa mediante una actualización de stack.

Guarda identificadores reales, resultados y costos en `.private/`, no en este documento. No ejecutes definiciones antiguas que vuelvan a declarar una base ya retirada.
