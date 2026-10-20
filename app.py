import streamlit as st

from src import auth, auth_ui

st.set_page_config(page_title="LV12 - Historico de Clientes", layout="wide")

usuario = auth.sesion_actual()
if usuario is None:
    # Sin sesion valida la navegacion tiene SOLO el login (las demas pantallas ni existen).
    paginas = [st.Page("pantallas/login.py", title="Ingresar", default=True)]
elif usuario["debe_cambiar_password"]:
    paginas = [st.Page("pantallas/cambiar_password.py", title="Elegí tu contraseña", default=True)]
else:
    paginas = [
        st.Page("pantallas/tablero.py", title="Tablero mensual", default=True),
        st.Page("pantallas/clientes_mes.py", title="Clientes por mes"),
        st.Page("pantallas/conciliacion.py", title="Conciliación contra el Excel"),
    ]

navegacion = st.navigation(paginas, position="sidebar" if len(paginas) > 1 else "hidden")
if usuario is not None:
    auth_ui.barra_lateral(usuario)
navegacion.run()
