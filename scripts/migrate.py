"""Aplica, en orden, los archivos .sql de sql/migrations/ que todavia no se aplicaron.

Uso: python scripts/migrate.py
Requiere DATABASE_URL en el entorno (ver .env.example).

Regla: una migracion ya aplicada NO se edita. Cualquier cambio de estructura va en una
migracion nueva (numerada a continuacion), asi el historial de la base es trazable.
"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


def main() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit(
            "Falta DATABASE_URL. Copia .env.example a .env y completa la URL de la base "
            "de Render (testing: lv12-historico-clientes-dev-db)."
        )

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename    TEXT PRIMARY KEY,
                    applied_en  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                print(f"  ya aplicada: {path.name}")
                continue
            print(f"aplicando: {path.name}")
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
                )
            conn.commit()

    print("listo.")


if __name__ == "__main__":
    main()
