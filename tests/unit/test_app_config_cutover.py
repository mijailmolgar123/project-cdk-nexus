import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("target_host", ["recovered.example", "original.example"])
@pytest.mark.parametrize("existing_facturation", [None, '{"FACTURACION_PRODUCTION_TOKEN":"edited-ssm-token"}'])
def test_secret_cutover_and_return_preserve_credentials_and_existing_tokens(monkeypatch, target_host, existing_facturation):
    secret = {
        "username": "test-user",
        "password": "test-only-password",
        "host": "previous.example",
        "secretKey": "test-only-session-key",
        "FACTURACION_PRODUCTION_TOKEN": "test-only-existing-token",
    }
    sm = Mock()
    sm.get_secret_value.return_value = {"SecretString": json.dumps(secret)}
    ssm = Mock()
    class MissingParameter(Exception):
        response = {"Error": {"Code": "ParameterNotFound"}}

    def get_parameter(**kwargs):
        if kwargs["Name"] == "/test/FACTURACION_CONFIG":
            if existing_facturation is None:
                raise MissingParameter()
            return {"Parameter": {"Value": existing_facturation}}
        return {"Parameter": {"Value": secret["secretKey"]}}

    ssm.get_parameter.side_effect = get_parameter
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(
        client=lambda service: sm if service == "secretsmanager" else ssm,
    ))
    monkeypatch.setitem(sys.modules, "botocore.exceptions", SimpleNamespace(ClientError=MissingParameter))
    path = Path(__file__).resolve().parents[2] / "lambda" / "app_config_parameters" / "index.py"
    spec = importlib.util.spec_from_file_location("app_config_cutover_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.handler({
        "RequestType": "Update",
        "ResourceProperties": {
            "DatabaseSecretArn": "test-secret-arn",
            "DatabaseHost": target_host,
            "DbPasswordParameterName": "/test/DB_PASSWORD",
            "SecretKeyParameterName": "/test/SECRET_KEY",
            "FacturacionParameterName": "/test/FACTURACION_CONFIG",
            "DatabaseSecretExtraValues": {
                "FACTURACION_PRODUCTION_TOKEN": "",
                "FACTURACION_ENV": "sandbox",
            },
        },
    }, None)
    payload = json.loads(sm.put_secret_value.call_args.kwargs["SecretString"])
    assert payload["host"] == target_host
    for key in ("username", "password", "secretKey", "FACTURACION_PRODUCTION_TOKEN"):
        assert payload[key] == secret[key]
    assert payload["FACTURACION_ENV"] == "sandbox"
    writes = [call.kwargs for call in ssm.put_parameter.call_args_list if call.kwargs["Name"] == "/test/FACTURACION_CONFIG"]
    if existing_facturation is None:
        assert len(writes) == 1
        assert writes[0]["Type"] == "SecureString"
        assert json.loads(writes[0]["Value"])["FACTURACION_PRODUCTION_TOKEN"] == secret["FACTURACION_PRODUCTION_TOKEN"]
    else:
        assert writes == []
