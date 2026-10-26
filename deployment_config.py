"""Merge optional, gitignored deployment settings before CDK creates constructs."""

import json
import os
from pathlib import Path


def merge_context(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_context(result[key], value)
        else:
            result[key] = value
    return result


def read_local_context() -> dict:
    configured_path = os.environ.get("CDK_LOCAL_CONFIG", "cdk.local.json")
    if not configured_path:
        return {}
    path = Path(configured_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    if not path.exists():
        if "CDK_LOCAL_CONFIG" in os.environ:
            raise ValueError("The selected local CDK configuration does not exist.")
        return {}
    data = json.loads(path.read_text())
    context = data.get("context")
    if not isinstance(context, dict):
        raise ValueError("Local CDK configuration requires a context object.")
    return context


def load_local_context(app) -> None:
    for key, value in read_local_context().items():
        # An explicit -c env_name=... still selects the requested environment.
        if key == "env_name" and app.node.try_get_context(key) is not None:
            continue
        existing = app.node.try_get_context(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            value = merge_context(existing, value)
        app.node.set_context(key, value)
