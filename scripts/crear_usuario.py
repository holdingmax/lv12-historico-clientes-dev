#!/usr/bin/env python
"""Crea un usuario de la herramienta (interactivo).

Uso: python scripts/crear_usuario.py
Pide email, nombre, rol y contrasena. La contrasena se lee con getpass: nunca se recibe por
argumento, no se muestra, no se imprime y no se guarda en ningun log. El usuario se crea con
"debe cambiar la contrasena" activado: en su primer ingreso elige una propia.
Requiere DATABASE_URL en el entorno (ver .env.example) y la migracion 004 aplicada.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # para poder importar src/

from src.auth import MIN_PASSWORD, ROLES, ErrorAuth, crear_usuario  # noqa: E402


def pedir_rol() -> str:
    while True:
        rol = input(f"Rol ({' / '.join(ROLES)}): ").strip().lower()
        if rol in ROLES:
            return rol
        print(f"Elegí uno de: {', '.join(ROLES)}.")


def pedir_password() -> str:
    while True:
        password = getpass.getpass(f"Contraseña temporal (mínimo {MIN_PASSWORD} caracteres): ")
        if password != getpass.getpass("Repetila: "):
            print("No coinciden. Probá de nuevo.")
            continue
        return password


def main() -> int:
    email = input("Email: ").strip()
    nombre = input("Nombre: ").strip()
    rol = pedir_rol()
    password = pedir_password()
    try:
        crear_usuario(email, nombre, rol, password)
    except ErrorAuth as e:
        print(f"No se creó el usuario: {e}")
        return 1
    except Exception:
        # Sin detalle tecnico: podria incluir datos de la conexion.
        print("No se creó el usuario: no se pudo escribir en la base. Revisá DATABASE_URL y las migraciones.")
        return 1
    print(f"Usuario creado: {email.lower()} ({rol}). En su primer ingreso va a tener que cambiar la contraseña.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
