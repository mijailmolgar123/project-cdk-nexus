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
        _delete_parameter(db_password_parameter)
        _delete_parameter(secret_key_parameter)
        return {"PhysicalResourceId": physical_resource_id}

    secret_payload = _read_database_secret(props["DatabaseSecretArn"])
    db_password = str(secret_payload["password"])

    _put_secure_parameter(db_password_parameter, db_password)

    secret_key = _get_existing_parameter(secret_key_parameter)
    if secret_key is None:
        secret_key = secrets.token_urlsafe(48)
        _put_secure_parameter(secret_key_parameter, secret_key)

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
