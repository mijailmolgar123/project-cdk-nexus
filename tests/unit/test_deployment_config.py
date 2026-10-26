import json

import aws_cdk as cdk
import pytest

from deployment_config import load_local_context, merge_context, read_local_context
from tools.check_public_files import findings


def test_local_configuration_overrides_examples_without_changing_environment_selection(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"context": {
        "project": "customapp", "env_name": "dev",
        "environments": {"prod": {"db_name": "custom_db"}},
    }}))
    monkeypatch.setenv("CDK_LOCAL_CONFIG", str(path))
    app = cdk.App(context={"project": "demoapp", "env_name": "prod", "environments": {
        "prod": {"db_name": "app_db", "region": "us-east-1"},
    }})
    load_local_context(app)
    assert app.node.try_get_context("env_name") == "prod"
    assert app.node.try_get_context("project") == "customapp"
    assert app.node.try_get_context("environments")["prod"] == {
        "db_name": "custom_db", "region": "us-east-1",
    }


def test_public_mode_never_reads_local_configuration(monkeypatch):
    monkeypatch.setenv("CDK_LOCAL_CONFIG", "")
    assert read_local_context() == {}


def test_explicit_missing_configuration_fails_instead_of_falling_back(monkeypatch, tmp_path):
    monkeypatch.setenv("CDK_LOCAL_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(ValueError, match="does not exist"):
        read_local_context()


def test_nested_overrides_preserve_unrelated_defaults():
    assert merge_context({"a": {"region": "x", "ids": [1]}}, {"a": {"ids": [2]}}) == {
        "a": {"region": "x", "ids": [2]},
    }


def test_privacy_check_rejects_private_files_and_non_example_accounts():
    assert findings(".private/inventory.json", "{}")
    assert findings("cdk.local.json", "{}")
    assert findings("config.json", '"account": "' + "987654" + "321098" + '"')
    assert not findings("cdk.local.example.json", '"account": "111111111111"')
