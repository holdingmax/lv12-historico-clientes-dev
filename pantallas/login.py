"""Pantalla de login."""
import streamlit as st

from src import auth, auth_ui


def main() -> None:
    if auth.sesion_actual() is not None:
        # Con sesion, app.py arma la navegacion con las demas pantallas y esta ni se ofrece.
        st.info("Ya iniciaste sesión.")
        st.stop()
    auth_ui.formulario_login()


main()
