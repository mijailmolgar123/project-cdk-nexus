# Registro De Lo Hecho Hasta Este Punto

Este documento deja trazabilidad del proceso seguido durante el despliegue en la cuenta nueva.

## 1. Preparación del repo local

Se dejó el repo alineado para trabajo por proyecto:

- `Makefile` usa `python3.11`
- `cdk.json` ejecuta CDK con `.venv/bin/python`
- se recreó `.venv` con Python `3.11.11`
- `make install`, `make test` y `make synth` quedaron funcionando localmente

## 2. Ajustes de configuración

Se confirmó y dejó configurado:

- `db_name = proyecto_cotizaciones`
- `db_username = postgres`
- `db_engine_version = 17.4`
- `app_system_packages` incluye `postgresql17`

También se quitó la dependencia de defaults silenciosos para `db_name` y `db_username` en `app.py`.

## 3. Verificación de perfiles AWS

Se revisaron perfiles locales y se confirmó:

- perfil original: `web-segurimax`
- perfil nuevo usado para la cuenta nueva: `cdk-nexus`

Cuenta objetivo verificada:

- `450963613767`

Región:

- `us-east-1`

## 4. Primer intento de despliegue

Se hizo:

```bash
AWS_PROFILE=cdk-nexus npx cdk bootstrap aws://450963613767/us-east-1
AWS_PROFILE=cdk-nexus make deploy ENV_NAME=dev
```

Resultado:

- `bootstrap` exitoso
- `network` y `compute` se crearon
- `database` falló

Motivo del fallo:

- RDS no aceptó un `DBSubnetGroup` con cobertura de solo una AZ

## 5. Corrección de VPC para RDS

Se identificó que `max_azs=1` no servía para RDS.

Se cambió en `cdk.json`:

- `max_azs: 2`

## 6. Segundo intento y conflicto de CIDR

Al redeplegar, aparecieron conflictos de subnets por haber intentado migrar una VPC ya creada de 1 AZ a 2 AZ.

Resultado:

- `network` quedó en `UPDATE_ROLLBACK_COMPLETE`
- `database` quedó en `ROLLBACK_COMPLETE`
- `compute` quedó en `CREATE_COMPLETE`

## 7. Limpieza y redeploy limpio

Se destruyeron los stacks del ambiente `dev` afectados:

- `segurimax-dev-scheduler`
- `segurimax-dev-database`
- `segurimax-dev-compute`
- `segurimax-dev-network`

Se conservó:

- `segurimax-github-actions`

Luego se relanzó el despliegue limpio del ambiente `dev`.

## 8. Despliegue exitoso de infraestructura

El despliegue limpio terminó bien y quedaron creados:

- `segurimax-github-actions`
- `segurimax-dev-network`
- `segurimax-dev-compute`
- `segurimax-dev-database`
- `segurimax-dev-scheduler`

Outputs relevantes:

- `GitHubActionsRoleArn = arn:aws:iam::450963613767:role/segurimax-github-actions-role`
- `DbEndpoint = segurimax-dev-rds.ck7skos6woqy.us-east-1.rds.amazonaws.com`
- `DbInstanceIdentifier = segurimax-dev-rds`
- `AppConfigParameterPrefix = /segurimax/dev/app-config`
- `InstanceId = i-02857015ce48c50da`
- `PublicDns = ec2-32-195-65-215.compute-1.amazonaws.com`

## 9. Verificación en EC2

Se verificó por SSM:

- `nginx` quedó `active (running)`
- `myapp` quedó `inactive (dead)`

Interpretación:

- la infraestructura base quedó correcta
- el servicio existe
- pero todavía faltaba desplegar la app y cargar su configuración

## 10. Deploy key y acceso al repo privado

Se generó una pareja de claves:

- pública
- privada

Uso definido:

- clave pública: subida a GitHub como Deploy Key del repo `proyecto-cotizaciones`
- clave privada: guardada en AWS SSM Parameter Store como:

```text
/proyecto-cotizaciones/dev/github/deploy-key
```

## 11. Preparación SSH en EC2 para leer GitHub

Ya dentro de la EC2 vía SSM se hizo:

- creación de `/home/ec2-user/.ssh`
- carga de `github.com` en `known_hosts`
- descarga de la private key desde Parameter Store a:
  - `/home/ec2-user/.ssh/deploy_key`
- ajuste de permisos `600`

Con eso quedó resuelto:

- el problema inicial de `Host key verification failed`
- el problema inicial de `Identity file ... not accessible`

## 12. Primer pull correcto del repo de aplicación

Después de dejar `known_hosts` y `deploy_key` correctos, se logró hacer el primer pull del repo privado desde la EC2.

Eso confirmó:

- acceso correcto de la EC2 al repo privado
- deploy key bien configurada en GitHub
- parámetro SSM correcto

## 13. Elastic IP

Se detectó que la EC2 no tenía Elastic IP asociada.

Se preparó el código para soportarla desde CDK:

- bandera `associate_elastic_ip` en `cdk.json`
- creación y asociación de `EIP` en `ComputeStack`
- output `ElasticIpAddress`

También se validó localmente:

- `make test`
- `make synth ENV_NAME=dev`

Hasta este punto el cambio quedó listo en código, pendiente de aplicar con un nuevo `cdk deploy` del stack `compute`.

## 14. Estado actual

La situación al cierre de este registro es:

- infraestructura base desplegada
- acceso por SSM funcionando
- acceso de la EC2 a GitHub funcionando
- parámetros SSM de app config creados
- RDS disponible
- app todavía pendiente de instalación final, restore y puesta en marcha
- Elastic IP pendiente de aplicar al stack si se desea IP fija
