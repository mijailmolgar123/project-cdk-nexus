import json
import logging
import secrets

import boto3
from botocore.exceptions import ClientError


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

secretsmanager_client = boto3.client("secretsmanager")
ssm_client = boto3.client("ssm")


def handler(event, _context):
    request_type = event["RequestType"]
    props = event["ResourceProperties"]

    db_password_parameter = props["DbPasswordParameterName"]
    secret_key_parameter = props["SecretKeyParameterName"]
    physical_resource_id = f"{db_password_parameter}|{secret_key_parameter}"

    LOGGER.info("Handling %s for %s", request_type, physical_resource_id)

    if request_type == "Delete":
        LOGGER.info("Preserving mirrored SSM parameters on delete.")
        return {"PhysicalResourceId": physical_resource_id}

    secret_payload = _read_database_secret(props["DatabaseSecretArn"])
    db_password = str(secret_payload["password"])

    _put_secure_parameter(db_password_parameter, db_password)

    secret_key = _get_existing_parameter(secret_key_parameter)
    if secret_key is None:
        secret_key = secrets.token_urlsafe(48)
        _put_secure_parameter(secret_key_parameter, secret_key)

    # Extra values initialize missing settings; a connection cutover must not
    # reset existing API tokens or other settings edited in Secrets Manager.
    database_secret_updates = {
        key: value for key, value in props.get("DatabaseSecretExtraValues", {}).items()
        if key not in secret_payload
    }
    database_secret_updates[props.get("DatabaseSecretKeyName", "secretKey")] = secret_key
    if props.get("DatabaseHost"):
        database_secret_updates["host"] = props["DatabaseHost"]

    _put_database_secret_values(
        props["DatabaseSecretArn"],
        database_secret_updates,
        secret_payload,
    )

    # Initialize once from the actual secret, including existing tokens and
    # empty optional fields. Subsequent deploys preserve Parameter Store edits.
    facturation_parameter = props.get("FacturacionParameterName")
    if facturation_parameter and _get_existing_parameter(facturation_parameter) is None:
        effective_payload = dict(secret_payload)
        effective_payload.update(database_secret_updates)
        facturation = effective_payload.get("facturacion", effective_payload)
        settings = {key: str(value) for key, value in facturation.items()
                    if key.startswith("FACTURACION_") and value is not None}
        _put_secure_parameter(facturation_parameter, json.dumps(settings, ensure_ascii=False))

    if request_type == "Update":
        old_props = event.get("OldResourceProperties", {})
        for previous_name in (
            old_props.get("DbPasswordParameterName"),
            old_props.get("SecretKeyParameterName"),
        ):
            if previous_name and previous_name not in {
                db_password_parameter,
                secret_key_parameter,
            }:
                _delete_parameter(previous_name)

    return {"PhysicalResourceId": physical_resource_id}


def _read_database_secret(secret_arn: str) -> dict:
    response = secretsmanager_client.get_secret_value(SecretId=secret_arn)
    return json.loads(response["SecretString"])


def _put_database_secret_values(
    secret_arn: str,
    values: dict,
    secret_payload: dict,
) -> None:
    changed_values = {
        str(key): str(value)
        for key, value in values.items()
        if secret_payload.get(str(key)) != str(value)
    }
    if not changed_values:
        return

    updated_payload = dict(secret_payload)
    updated_payload.update(changed_values)
    secretsmanager_client.put_secret_value(
        SecretId=secret_arn,
        SecretString=json.dumps(updated_payload, separators=(",", ":")),
    )


def _get_existing_parameter(name: str) -> str | None:
    try:
        response = ssm_client.get_parameter(Name=name, WithDecryption=True)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ParameterNotFound":
            raise
        return None
    return response["Parameter"]["Value"]


def _put_secure_parameter(name: str, value: str) -> None:
    ssm_client.put_parameter(
        Name=name,
        Value=value,
        Type="SecureString",
        Tier="Standard",
        Overwrite=True,
    )


def _delete_parameter(name: str) -> None:
    try:
        ssm_client.delete_parameter(Name=name)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ParameterNotFound":
            raise
