"""Pantalla de cambio obligatorio de contraseña (primer ingreso o contraseña temporal)."""
import streamlit as st

from src import auth, auth_ui


def main() -> None:
    usuario = auth.sesion_actual()
    if usuario is None:
        auth_ui.formulario_login()
        st.stop()
    auth_ui.formulario_cambio_password(usuario)


main()
