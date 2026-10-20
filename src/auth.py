"""Login propio de la herramienta: usuarios, contrasenas, bloqueo y sesion.

Cada herramienta tiene su propio login (Toolbox solo es la puerta de entrada).
- Contrasenas: solo se guarda el hash bcrypt. Nunca se imprimen, se loguean ni se guardan en claro.
- Las escrituras (usuario, acceso_log) pasan SOLO por `_conexion_escritura`, privada de este modulo.
  Las pantallas siguen usando la conexion de solo lectura de src/db.py.
- El mensaje de login incorrecto es siempre el mismo, exista o no el email.
"""
import os
import re
import secrets
import time
from functools import lru_cache

import bcrypt
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from src.db import BaseNoConfigurada, get_connection_lectura

MENSAJE_LOGIN_INCORRECTO = "Usuario o contraseña incorrectos"
MAX_INTENTOS = 5                    # fallos seguidos que bloquean la cuenta
BLOQUEO_MINUTOS = 15
INACTIVIDAD_SEGUNDOS = 60 * 60      # la sesion vence a los 60 minutos sin actividad
REVALIDAR_CADA_SEGUNDOS = 5 * 60    # cada tanto se confirma que el usuario sigue activo
MIN_PASSWORD = 10
MAX_PASSWORD_BYTES = 72             # limite de bcrypt
ROLES = ("administrador", "operador")
TEXTO_ROL = {"administrador": "Administrador", "operador": "Operador"}

CLAVE_USUARIO = "auth_usuario"
CLAVE_ACTIVIDAD = "auth_ultima_actividad"
CLAVE_REVALIDADO = "auth_revalidado_en"
CLAVE_AVISO = "auth_aviso"

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_CAMPOS_SESION = ("id", "email", "nombre", "rol", "debe_cambiar_password")


class ErrorAuth(Exception):
    """Error que se le puede mostrar tal cual a la persona (no contiene datos tecnicos)."""


def _ahora() -> float:
    return time.time()


# ---------------------------------------------------------------- contrasenas

def validar_password_nueva(password: str) -> str | None:
    """Devuelve el motivo si la contrasena no sirve, o None si esta bien."""
    if len(password) < MIN_PASSWORD:
        return f"La contraseña tiene que tener al menos {MIN_PASSWORD} caracteres."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"La contraseña es demasiado larga (máximo {MAX_PASSWORD_BYTES} caracteres)."
    return None


def hashear_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # contrasena de mas de 72 bytes o hash mal formado
        return False


@lru_cache(maxsize=1)
def _hash_falso() -> str:
    """Hash de relleno: cuando el email no existe se verifica igual, para no delatarlo por el tiempo."""
    return hashear_password(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- base de datos

def _conexion_escritura() -> psycopg.Connection:
    """Conexion con permiso de escritura. Privada de auth: usar como `with` (commit/rollback)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise BaseNoConfigurada(
            "Falta configurar la conexion a la base de datos (variable DATABASE_URL)."
        )
    return psycopg.connect(url, row_factory=dict_row)


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def crear_usuario(email: str, nombre: str, rol: str, password: str) -> int:
    """Crea un usuario con debe_cambiar_password = true. Devuelve su id."""
    email = normalizar_email(email)
    nombre = (nombre or "").strip()
    if not _EMAIL.fullmatch(email):
        raise ErrorAuth("El email no es válido.")
    if not nombre:
        raise ErrorAuth("Falta el nombre.")
    if rol not in ROLES:
        raise ErrorAuth(f"El rol tiene que ser uno de: {', '.join(ROLES)}.")
    motivo = validar_password_nueva(password)
    if motivo:
        raise ErrorAuth(motivo)
    try:
        with _conexion_escritura() as conn:
            fila = conn.execute(
                "INSERT INTO usuario (email, nombre, password_hash, rol, debe_cambiar_password) "
                "VALUES (%s, %s, %s, %s, TRUE) RETURNING id",
                (email, nombre, hashear_password(password), rol),
            ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise ErrorAuth("Ya existe un usuario con ese email.") from None
    return fila["id"]


def _registrar(conn, usuario_id, email_intentado: str, resultado: str) -> None:
    conn.execute(
        "INSERT INTO acceso_log (usuario_id, email_intentado, resultado) VALUES (%s, %s, %s)",
        (usuario_id, email_intentado[:254], resultado),
    )


def autenticar(email: str, password: str) -> dict | None:
    """Devuelve los datos del usuario si el login es correcto; si no, None.

    No distingue email inexistente, usuario inactivo, cuenta bloqueada ni contrasena mala.
    Cada intento queda en acceso_log (sin la contrasena)."""
    email = normalizar_email(email)
    with _conexion_escritura() as conn:
        u = conn.execute(
            "SELECT id, email, nombre, password_hash, rol, activo, debe_cambiar_password, "
            "       intentos_fallidos, (bloqueado_hasta IS NOT NULL AND bloqueado_hasta > now()) AS bloqueado "
            "FROM usuario WHERE email = %s FOR UPDATE",
            (email,),
        ).fetchone()

        if u is None:
            verificar_password(password, _hash_falso())
            _registrar(conn, None, email, "fallo")
            return None
        if u["bloqueado"]:
            verificar_password(password, _hash_falso())
            _registrar(conn, u["id"], email, "bloqueado")
            return None
        if not u["activo"]:
            verificar_password(password, _hash_falso())
            _registrar(conn, u["id"], email, "fallo")
            return None

        if verificar_password(password, u["password_hash"]):
            conn.execute(
                "UPDATE usuario SET intentos_fallidos = 0, bloqueado_hasta = NULL, "
                "ultimo_acceso = now() WHERE id = %s", (u["id"],),
            )
            _registrar(conn, u["id"], email, "ok")
            return {k: u[k] for k in _CAMPOS_SESION}

        intentos = u["intentos_fallidos"] + 1
        if intentos >= MAX_INTENTOS:
            conn.execute(
                "UPDATE usuario SET intentos_fallidos = 0, "
                "bloqueado_hasta = now() + make_interval(mins => %s) WHERE id = %s",
                (BLOQUEO_MINUTOS, u["id"]),
            )
        else:
            conn.execute(
                "UPDATE usuario SET intentos_fallidos = %s WHERE id = %s", (intentos, u["id"])
            )
        _registrar(conn, u["id"], email, "fallo")
        return None


def cambiar_password(usuario_id: int, actual: str, nueva: str) -> None:
    """Cambia la contrasena (verificando la actual) y apaga debe_cambiar_password."""
    motivo = validar_password_nueva(nueva)
    if motivo:
        raise ErrorAuth(motivo)
    with _conexion_escritura() as conn:
        u = conn.execute(
            "SELECT password_hash FROM usuario WHERE id = %s AND activo FOR UPDATE", (usuario_id,)
        ).fetchone()
        if u is None or not verificar_password(actual, u["password_hash"]):
            raise ErrorAuth("La contraseña actual no es correcta.")
        if verificar_password(nueva, u["password_hash"]):
            raise ErrorAuth("La contraseña nueva tiene que ser distinta de la actual.")
        conn.execute(
            "UPDATE usuario SET password_hash = %s, debe_cambiar_password = FALSE WHERE id = %s",
            (hashear_password(nueva), usuario_id),
        )


# ---------------------------------------------------------------- sesion

def iniciar_sesion(usuario: dict) -> None:
    ahora = _ahora()
    st.session_state[CLAVE_USUARIO] = {k: usuario[k] for k in _CAMPOS_SESION}
    st.session_state[CLAVE_ACTIVIDAD] = ahora
    st.session_state[CLAVE_REVALIDADO] = ahora


def cerrar_sesion(aviso: str | None = None) -> None:
    for clave in (CLAVE_USUARIO, CLAVE_ACTIVIDAD, CLAVE_REVALIDADO):
        st.session_state.pop(clave, None)
    if aviso:
        st.session_state[CLAVE_AVISO] = aviso


def _revalidar(usuario: dict) -> dict | None:
    """Confirma en la base que el usuario sigue activo y actualiza rol/nombre.
    Si la base no responde se mantiene la sesion (se reintenta en la proxima vuelta)."""
    try:
        with get_connection_lectura().cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, email, nombre, rol, activo, debe_cambiar_password FROM usuario WHERE id = %s",
                (usuario["id"],),
            )
            fila = cur.fetchone()
    except Exception:
        return usuario
    if fila is None or not fila["activo"]:
        return None
    return {k: fila[k] for k in _CAMPOS_SESION}


def sesion_actual() -> dict | None:
    """Usuario con sesion valida, o None. Cada llamada cuenta como actividad."""
    usuario = st.session_state.get(CLAVE_USUARIO)
    if usuario is None:
        return None
    ahora = _ahora()
    if ahora - st.session_state.get(CLAVE_ACTIVIDAD, 0) > INACTIVIDAD_SEGUNDOS:
        cerrar_sesion("La sesión venció por inactividad. Ingresá de nuevo.")
        return None
    st.session_state[CLAVE_ACTIVIDAD] = ahora
    if ahora - st.session_state.get(CLAVE_REVALIDADO, 0) > REVALIDAR_CADA_SEGUNDOS:
        actualizado = _revalidar(usuario)
        if actualizado is None:
            cerrar_sesion("Tu usuario ya no tiene acceso. Consultá con un administrador.")
            return None
        st.session_state[CLAVE_USUARIO] = usuario = actualizado
        st.session_state[CLAVE_REVALIDADO] = ahora
    return usuario


def require_login() -> dict:
    """Primera linea de cada pantalla: sin sesion valida muestra el login y corta la ejecucion
    (antes de cualquier consulta). Si falta cambiar la contrasena, muestra solo esa pantalla."""
    from src import auth_ui  # import tardio: auth_ui usa este modulo

    usuario = sesion_actual()
    if usuario is None:
        auth_ui.formulario_login()
        st.stop()
    if usuario["debe_cambiar_password"]:
        auth_ui.formulario_cambio_password(usuario)
        st.stop()
    return usuario
