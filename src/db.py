"""Acceso a la base PostgreSQL del proyecto (Render)."""
import os

import psycopg
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


class BaseNoConfigurada(Exception):
    """Falta la variable DATABASE_URL."""


@st.cache_resource
def get_connection() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise BaseNoConfigurada(
            "Falta configurar la conexion a la base de datos (variable DATABASE_URL)."
        )
    return psycopg.connect(url, autocommit=True)


def estado_base() -> tuple[bool, str]:
    """Devuelve (ok, mensaje) para mostrar en pantalla, sin errores tecnicos crudos."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            n = cur.fetchone()[0]
        return True, f"Base conectada. Migraciones aplicadas: {n}."
    except BaseNoConfigurada as e:
        return False, str(e)
    except psycopg.errors.UndefinedTable:
        return True, "Base conectada, todavia sin migraciones. Ejecuta: python scripts/migrate.py"
    except Exception:
        return False, "No se pudo conectar a la base. Revisa que DATABASE_URL sea correcta."
