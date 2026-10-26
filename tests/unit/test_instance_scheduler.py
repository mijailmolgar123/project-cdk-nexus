import importlib.util
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def load_scheduler(monkeypatch, manage_rds=None):
    monkeypatch.setenv("EC2_INSTANCE_ID", "i-example")
    monkeypatch.setenv("RDS_INSTANCE_IDENTIFIER", "demoapp-dev-rds-recovery")
    if manage_rds is None:
        monkeypatch.delenv("MANAGE_RDS", raising=False)
    else:
        monkeypatch.setenv("MANAGE_RDS", manage_rds)
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=Mock()))
    monkeypatch.setitem(sys.modules, "botocore.exceptions", SimpleNamespace(ClientError=Exception))
    path = Path(__file__).resolve().parents[2] / "lambda" / "instance_scheduler" / "index.py"
    spec = importlib.util.spec_from_file_location("instance_scheduler_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._change_ec2_state = Mock(return_value="ec2-requested")
    module._change_rds_state = Mock(return_value="rds-requested")
    return module


@pytest.mark.parametrize("action", ["start", "stop"])
def test_rds_can_stay_running_while_ec2_keeps_its_schedule(monkeypatch, action):
    module = load_scheduler(monkeypatch, "false")
    assert module.handler({"action": action}, None)["rds"] == "not-managed"
    module._change_ec2_state.assert_called_once_with(action)
    module._change_rds_state.assert_not_called()


def test_default_scheduler_behavior_is_preserved(monkeypatch):
    module = load_scheduler(monkeypatch)
    assert module.handler({"action": "stop"}, None)["rds"] == "rds-requested"
    module._change_rds_state.assert_called_once_with("stop")


def test_database_start_does_not_start_ec2(monkeypatch):
    module = load_scheduler(monkeypatch, "true")
    assert module.handler({"action": "start", "resource": "rds"}, None)["ec2"] == "not-targeted"
    module._change_ec2_state.assert_not_called()
    module._change_rds_state.assert_called_once_with("start")


def test_ec2_start_waits_for_database(monkeypatch):
    module = load_scheduler(monkeypatch, "true")
    module._get_rds_state = Mock(return_value="starting")
    with pytest.raises(RuntimeError, match="not ready"):
        module.handler({"action": "start", "resource": "ec2"}, None)
    module._change_ec2_state.assert_not_called()
    module._get_rds_state.return_value = "available"
    module.handler({"action": "start", "resource": "ec2"}, None)
    module._change_ec2_state.assert_called_once_with("start")
    module._change_rds_state.assert_not_called()


def test_database_stop_requires_ec2_stopped(monkeypatch):
    module = load_scheduler(monkeypatch, "true")
    module._get_ec2_state = Mock(return_value="stopping")
    with pytest.raises(RuntimeError, match="EC2 must be stopped"):
        module.handler({"action": "stop", "resource": "rds"}, None)
    module._change_rds_state.assert_not_called()
    module._get_ec2_state.return_value = "stopped"
    module.handler({"action": "stop", "resource": "rds"}, None)
    module._change_rds_state.assert_called_once_with("stop")


def test_stale_scheduled_start_never_changes_resources(monkeypatch):
    module = load_scheduler(monkeypatch, "true")
    scheduled = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    result = module.handler({"action": "start", "resource": "rds", "scheduled_at": scheduled}, None)
    assert result["status"] == "ignored-stale-event"
    module._change_ec2_state.assert_not_called()
    module._change_rds_state.assert_not_called()
