import json
import os
import re
from typing import Any

import pg8000.dbapi
from werkzeug.security import generate_password_hash


class BadRequest(Exception):
    pass


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _connect():
    return pg8000.dbapi.connect(
        host=_required_env("DB_HOST"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=_required_env("DB_NAME"),
        user=_required_env("DB_USER"),
        password=_required_env("DB_PASSWORD"),
        timeout=5,
    )


def _parse_event(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    action = event.get("action")
    payload = event.get("payload", {})

    if not isinstance(action, str) or not action:
        raise BadRequest("Field 'action' is required.")
    if not isinstance(payload, dict):
        raise BadRequest("Field 'payload' must be an object.")

    return action, payload


def _required_payload(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"Field 'payload.{key}' is required.")
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str, max_length: int) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadRequest(f"Field 'payload.{key}' must be a string or null.")
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise BadRequest(f"Field 'payload.{key}' must be at most {max_length} characters.")
    return value


def _list_users(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT id, nombre_usuario, nombre_completo, correo_corporativo, area,
               rol, fecha_de_registro, activo, fecha_de_baja
        FROM usuario
        ORDER BY id
        """
    )
    return [
        {
            "id": row[0],
            "username": row[1],
            "full_name": row[2],
            "corporate_email": row[3],
            "area": row[4],
            "role": row[5],
            "registered_at": row[6].isoformat() if row[6] else None,
            "active": row[7],
            "deactivated_at": row[8].isoformat() if row[8] else None,
        }
        for row in cursor.fetchall()
    ]


def _create_user(cursor, payload: dict[str, Any]) -> dict[str, Any]:
    username = _required_payload(payload, "username")
    if not re.fullmatch(r"[a-z0-9]+(?:\.[a-z0-9]+)*", username):
        raise BadRequest(
            "Field 'payload.username' must use lowercase letters, numbers, and dots."
        )
    password = _required_payload(payload, "password")
    role = _required_payload(payload, "role")
    if len(role) > 50:
        raise BadRequest("Field 'payload.role' must be at most 50 characters.")
    full_name = _optional_text(payload, "full_name", 150)
    corporate_email = _optional_text(payload, "corporate_email", 254)
    if corporate_email:
        corporate_email = corporate_email.lower()
    area = _optional_text(payload, "area", 50)

    password_hash = generate_password_hash(password)
    cursor.execute(
        """
        INSERT INTO usuario (
            nombre_usuario, nombre_completo, correo_corporativo, area,
            "contraseña_hash", rol, activo, fecha_de_registro
        )
        VALUES (%s, %s, %s, %s, %s, %s, true, CURRENT_TIMESTAMP)
        ON CONFLICT DO NOTHING
        RETURNING id, nombre_usuario, nombre_completo, correo_corporativo,
                  area, rol, activo
        """,
        [username, full_name, corporate_email, area, password_hash, role],
    )
    row = cursor.fetchone()
    if not row:
        raise BadRequest("Username or corporate email already exists.")
    return {
        "id": row[0],
        "username": row[1],
        "full_name": row[2],
        "corporate_email": row[3],
        "area": row[4],
        "role": row[5],
        "active": row[6],
    }


def _update_user(cursor, payload: dict[str, Any]) -> dict[str, Any]:
    username = _required_payload(payload, "username")
    updates = []
    values = []

    if "new_username" in payload:
        new_username = _required_payload(payload, "new_username")
        if not re.fullmatch(r"[a-z0-9]+(?:\.[a-z0-9]+)*", new_username):
            raise BadRequest(
                "Field 'payload.new_username' must use lowercase letters, numbers, and dots."
            )
        cursor.execute(
            "SELECT 1 FROM usuario WHERE nombre_usuario = %s AND nombre_usuario <> %s",
            [new_username, username],
        )
        if cursor.fetchone():
            raise BadRequest("The new username already exists.")
        updates.append("nombre_usuario = %s")
        values.append(new_username)

    if "password" in payload:
        password = _required_payload(payload, "password")
        updates.append('"contraseña_hash" = %s')
        values.append(generate_password_hash(password))

    if "role" in payload:
        role = _required_payload(payload, "role")
        if len(role) > 50:
            raise BadRequest("Field 'payload.role' must be at most 50 characters.")
        updates.append("rol = %s")
        values.append(role)

    if "active" in payload:
        active = payload["active"]
        if not isinstance(active, bool):
            raise BadRequest("Field 'payload.active' must be boolean.")
        updates.append("activo = %s")
        values.append(active)

    for key, column, max_length in (
        ("full_name", "nombre_completo", 150),
        ("corporate_email", "correo_corporativo", 254),
        ("area", "area", 50),
    ):
        if key in payload:
            value = _optional_text(payload, key, max_length)
            if key == "corporate_email" and value:
                value = value.lower()
            updates.append(f"{column} = %s")
            values.append(value)

    if not updates:
        raise BadRequest(
            "At least one of new_username, password, role, active, full_name, corporate_email, or area is required."
        )

    values.append(username)
    cursor.execute(
        f"""
        UPDATE usuario
        SET {", ".join(updates)}
        WHERE nombre_usuario = %s
        RETURNING id, nombre_usuario, rol, activo
        """,
        values,
    )
    row = cursor.fetchone()
    if not row:
        raise BadRequest(f"User not found: {username}")

    return {
        "id": row[0],
        "username": row[1],
        "role": row[2],
        "active": row[3],
    }


def _set_user_active(cursor, payload: dict[str, Any], active: bool) -> dict[str, Any]:
    username = _required_payload(payload, "username")
    cursor.execute(
        """
        UPDATE usuario
        SET activo = %s
        WHERE nombre_usuario = %s
        RETURNING id, nombre_usuario, rol, activo
        """,
        [active, username],
    )
    row = cursor.fetchone()
    if not row:
        raise BadRequest(f"User not found: {username}")

    return {
        "id": row[0],
        "username": row[1],
        "role": row[2],
        "active": row[3],
    }


def handler(event, context):
    try:
        action, payload = _parse_event(event or {})

        with _connect() as connection:
            cursor = connection.cursor()
            try:
                if action == "list_users":
                    result = _list_users(cursor)
                elif action == "create_user":
                    result = _create_user(cursor, payload)
                elif action == "update_user":
                    result = _update_user(cursor, payload)
                elif action == "disable_user":
                    result = _set_user_active(cursor, payload, False)
                elif action == "enable_user":
                    result = _set_user_active(cursor, payload, True)
                else:
                    raise BadRequest(f"Unsupported action: {action}")
            finally:
                cursor.close()
            connection.commit()

        return {
            "ok": True,
            "action": action,
            "result": result,
        }
    except BadRequest as exc:
        return {
            "ok": False,
            "error": str(exc),
        }
