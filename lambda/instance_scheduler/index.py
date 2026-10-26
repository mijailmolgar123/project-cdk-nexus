import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

EC2_INSTANCE_ID = os.environ["EC2_INSTANCE_ID"]
RDS_INSTANCE_IDENTIFIER = os.environ["RDS_INSTANCE_IDENTIFIER"]
MANAGE_RDS = os.environ.get("MANAGE_RDS", "true").lower() == "true"

ec2_client = boto3.client("ec2")
rds_client = boto3.client("rds")


def handler(event, _context):
    action = (event or {}).get("action")
    if action not in {"start", "stop"}:
        raise ValueError("Expected event.action to be 'start' or 'stop'.")
    resource = event.get("resource", "all")
    if resource not in {"ec2", "rds", "all"}:
        raise ValueError("Expected resource ec2, rds or all.")
    scheduled_at = event.get("scheduled_at")
    if scheduled_at:
        scheduled = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        if scheduled.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone.")
        age = (datetime.now(timezone.utc) - scheduled).total_seconds()
        if age > 300 or age < -60:
            LOGGER.warning("Ignoring stale or future schedule event")
            return {"action": action, "resource": resource, "status": "ignored-stale-event"}

    # Separate schedules start the database before the web server and stop it
    # only after EC2 is stopped. Never expose a server with an unavailable DB.
    if resource == "ec2" and action == "start" and MANAGE_RDS:
        if _get_rds_state() != "available":
            raise RuntimeError("Database is not ready; EC2 start deferred.")
    if resource == "rds" and action == "stop" and MANAGE_RDS:
        if _get_ec2_state() != "stopped":
            raise RuntimeError("EC2 must be stopped before stopping the database.")

    LOGGER.info(
        "Processing %s for EC2 instance %s and RDS instance %s",
        action,
        EC2_INSTANCE_ID,
        RDS_INSTANCE_IDENTIFIER,
    )

    result = {
        "action": action,
        "ec2": _change_ec2_state(action) if resource in {"ec2", "all"} else "not-targeted",
        "rds": (_change_rds_state(action) if MANAGE_RDS else "not-managed")
        if resource in {"rds", "all"} else "not-targeted",
    }
    LOGGER.info("Scheduler result: %s", json.dumps(result))
    return result


def _change_ec2_state(action: str) -> str:
    current_state = _get_ec2_state()
    if action == "start" and current_state in {"running", "pending"}:
        return _transition_status(current_state, "running")
    if action == "stop" and current_state in {"stopped", "stopping"}:
        return _transition_status(current_state, "stopped")

    try:
        if action == "start":
            ec2_client.start_instances(InstanceIds=[EC2_INSTANCE_ID])
            return "start-requested"
        ec2_client.stop_instances(InstanceIds=[EC2_INSTANCE_ID])
        return "stop-requested"
    except ClientError as error:
        if error.response.get("Error", {}).get("Code", "") != "IncorrectInstanceState":
            raise

        current_state = _get_ec2_state()
        if action == "start" and current_state in {"running", "pending"}:
            return _transition_status(current_state, "running")
        if action == "stop" and current_state in {"stopped", "stopping"}:
            return _transition_status(current_state, "stopped")
        raise


def _change_rds_state(action: str) -> str:
    current_state = _get_rds_state()
    if action == "start" and current_state in {"available", "starting"}:
        return _transition_status(current_state, "available")
    if action == "stop" and current_state in {"stopped", "stopping"}:
        return _transition_status(current_state, "stopped")

    try:
        if action == "start":
            rds_client.start_db_instance(DBInstanceIdentifier=RDS_INSTANCE_IDENTIFIER)
            return "start-requested"
        rds_client.stop_db_instance(DBInstanceIdentifier=RDS_INSTANCE_IDENTIFIER)
        return "stop-requested"
    except ClientError as error:
        if error.response.get("Error", {}).get("Code", "") != "InvalidDBInstanceState":
            raise

        current_state = _get_rds_state()
        if action == "start" and current_state in {"available", "starting"}:
            return _transition_status(current_state, "available")
        if action == "stop" and current_state in {"stopped", "stopping"}:
            return _transition_status(current_state, "stopped")
        raise


def _get_ec2_state() -> str:
    response = ec2_client.describe_instances(InstanceIds=[EC2_INSTANCE_ID])
    return response["Reservations"][0]["Instances"][0]["State"]["Name"]


def _get_rds_state() -> str:
    response = rds_client.describe_db_instances(
        DBInstanceIdentifier=RDS_INSTANCE_IDENTIFIER
    )
    return response["DBInstances"][0]["DBInstanceStatus"]


def _transition_status(current_state: str, target_state: str) -> str:
    if current_state == target_state:
        return "already-in-target-state"
    return "transition-in-progress"
