"""Formularios y barra lateral del login. La logica esta en src/auth.py."""
import streamlit as st

from src import auth
from src.db import BaseNoConfigurada
from src.formato import md


def formulario_login() -> None:
    st.title("Ingresar")
    st.caption("Radio LV12 · Histórico y evolución de facturación a clientes")
    aviso = st.session_state.pop(auth.CLAVE_AVISO, None)
    if aviso:
        st.info(aviso)
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        enviar = st.form_submit_button("Ingresar")
    st.caption(
        f"Después de {auth.MAX_INTENTOS} intentos fallidos seguidos, el acceso se bloquea "
        f"{auth.BLOQUEO_MINUTOS} minutos."
    )
    if not enviar:
        return
    try:
        usuario = auth.autenticar(email, password)
    except BaseNoConfigurada as e:
        st.error(str(e))
        return
    except Exception:
        # No se muestra el detalle tecnico: podria incluir datos de la conexion.
        st.error("No se pudo verificar el acceso. Probá de nuevo en un momento.")
        return
    if usuario is None:
        st.error(auth.MENSAJE_LOGIN_INCORRECTO)
        return
    auth.iniciar_sesion(usuario)
    st.rerun()


def formulario_cambio_password(usuario: dict) -> None:
    st.title("Elegí tu contraseña")
    st.info(
        "Por seguridad, antes de usar la herramienta tenés que reemplazar la contraseña "
        f"temporal por una tuya. Mínimo {auth.MIN_PASSWORD} caracteres."
    )
    with st.form("cambio_password"):
        actual = st.text_input("Contraseña actual (la temporal)", type="password")
        nueva = st.text_input("Contraseña nueva", type="password")
        repetir = st.text_input("Repetí la contraseña nueva", type="password")
        enviar = st.form_submit_button("Guardar contraseña")
    if not enviar:
        return
    if nueva != repetir:
        st.error("Las contraseñas nuevas no coinciden.")
        return
    try:
        auth.cambiar_password(usuario["id"], actual, nueva)
    except auth.ErrorAuth as e:
        st.error(str(e))
        return
    except Exception:
        st.error("No se pudo guardar la contraseña. Probá de nuevo en un momento.")
        return
    st.session_state[auth.CLAVE_USUARIO]["debe_cambiar_password"] = False
    st.toast("Contraseña actualizada.")
    st.rerun()


def barra_lateral(usuario: dict) -> None:
    """Nombre, rol y 'Cerrar sesion' en el costado."""
    with st.sidebar:
        st.markdown(f"**{md(usuario['nombre'])}**")
        st.caption(auth.TEXTO_ROL.get(usuario["rol"], usuario["rol"]))
        if st.button("Cerrar sesión", key="cerrar_sesion"):
            auth.cerrar_sesion()
            st.rerun()
