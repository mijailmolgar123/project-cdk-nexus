"""Read-only recovery checks. Run from an EC2 host that can reach private RDS."""

import argparse
import ast
import json
import re
import sys
from importlib.metadata import version
from pathlib import Path

import boto3
import psycopg2
from psycopg2 import sql
from sqlalchemy import URL, create_engine, inspect, text


def expected_columns(app_path: str) -> dict:
    """Inspect model declarations without importing startup code or running DDL."""
    tree = ast.parse(Path(app_path).read_text(encoding="utf-8-sig"))
    models = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(isinstance(base, ast.Attribute) and base.attr == "Model"
                   and isinstance(base.value, ast.Name) and base.value.id == "db"
                   for base in node.bases):
            continue
        table = re.sub(r"(?<!^)(?=[A-Z])", "_", node.name).lower()
        columns = []
        for item in node.body:
            if not isinstance(item, ast.Assign) or len(item.targets) != 1:
                continue
            target = item.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id == "__tablename__" and isinstance(item.value, ast.Constant):
                table = item.value.value
            value = item.value
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "Column" and isinstance(value.func.value, ast.Name)
                    and value.func.value.id == "db"):
                name = target.id
                if value.args and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str):
                    name = value.args[0].value
                columns.append(name)
        models[table] = columns
    return models


def validate(host: str, secret_id: str, region: str, app_path: str | None = None) -> dict:
    # Credentials stay in memory on the client host, never in CLI arguments/logs.
    response = boto3.client("secretsmanager", region_name=region).get_secret_value(
        SecretId=secret_id,
    )
    secret = json.loads(response["SecretString"])
    database = secret["dbname"]
    user = secret.get("username", "postgres")
    port = int(secret.get("port", 5432))
    options = "-c default_transaction_read_only=on -c statement_timeout=60000"
    connection = psycopg2.connect(
        host=host, port=port, dbname=database, user=user,
        password=secret["password"], sslmode="require", connect_timeout=15,
        options=options,
    )
    report = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version'), current_database(), "
                           "current_setting('transaction_read_only')")
            server_version, name, readonly = cursor.fetchone()
            report.update(server_version=server_version, database=name, read_only=readonly)
            cursor.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
            report["tls"] = cursor.fetchone()[0]
            cursor.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
            report["extensions"] = cursor.fetchall()
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            tables = {row[0] for row in cursor.fetchall()}
            report["public_table_count"] = len(tables)
            report["counts"] = {}
            for table in ("usuario", "cliente", "producto", "cotizacion", "orden_venta",
                          "guia_remision", "caso_cobranza", "cobro"):
                if table in tables:
                    cursor.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table)))
                    report["counts"][table] = cursor.fetchone()[0]
            if "alembic_version" in tables:
                cursor.execute("SELECT version_num FROM public.alembic_version")
                report["migration_revisions"] = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
            report["invalid_indexes"] = cursor.fetchone()[0]
            cursor.execute("SELECT am.amname, count(*) FROM pg_class c "
                           "JOIN pg_am am ON am.oid=c.relam "
                           "JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='public' AND c.relkind='i' "
                           "GROUP BY am.amname ORDER BY am.amname")
            report["index_methods"] = cursor.fetchall()
            cursor.execute("SELECT count(*) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
                           "WHERE k.contype='f' AND k.conrelid=k.confrelid AND c.relkind='p'")
            report["self_referencing_partitioned_foreign_keys"] = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM pg_collation WHERE collversion IS NOT NULL "
                           "AND collversion IS DISTINCT FROM pg_collation_actual_version(oid)")
            report["collation_version_mismatches"] = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM pg_prepared_xacts")
            report["prepared_transactions"] = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM pg_replication_slots WHERE slot_type='logical'")
            report["logical_replication_slots"] = cursor.fetchone()[0]
        connection.rollback()
    finally:
        connection.close()

    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=user, password=secret["password"],
        host=host, port=port, database=database,
    ), connect_args={"sslmode": "require", "options": options, "connect_timeout": 15})
    try:
        with engine.connect() as conn:
            report["sqlalchemy_read_only"] = conn.scalar(text("SHOW transaction_read_only"))
            inspector = inspect(conn)
            report["sqlalchemy_tables"] = len(inspector.get_table_names(schema="public"))
            report["sqlalchemy_product_columns"] = len(inspector.get_columns("producto", schema="public")) if "producto" in tables else 0
            currency_columns = {item["name"] for item in inspector.get_columns("orden_venta", schema="public")} if "orden_venta" in tables else set()
            report["sales_currency_columns"] = sorted(currency_columns & {"moneda", "valor_cambio"})
            if app_path:
                models = expected_columns(app_path)
                report["deployed_model_count"] = len(models)
                report["missing_deployed_model_columns"] = {}
                for table, expected in models.items():
                    actual = {item["name"] for item in inspector.get_columns(table, schema="public")} if table in tables else set()
                    missing = sorted(set(expected) - actual)
                    if missing:
                        report["missing_deployed_model_columns"][table] = missing
            report["client_versions"] = {name: version(name) for name in ("psycopg2-binary", "SQLAlchemy")}
            conn.rollback()
    finally:
        engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--secret-id", required=True)
    parser.add_argument("--app-path", help="Optional deployed app.py to inspect without importing it")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.host, args.secret_id, args.region, args.app_path), indent=2))
        return 0
    except Exception as error:
        # Don't print connection URLs, passwords, secret payloads or row contents.
        print(json.dumps({"error_type": type(error).__name__,
                          "sqlstate": getattr(error, "pgcode", None)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
