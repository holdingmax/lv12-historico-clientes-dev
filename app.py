import streamlit as st

st.set_page_config(page_title="LV12 - Historico de Clientes", layout="wide")

pantallas = st.navigation([
    st.Page("pantallas/tablero.py", title="Tablero mensual", default=True),
    st.Page("pantallas/clientes_mes.py", title="Clientes por mes"),
    st.Page("pantallas/conciliacion.py", title="Conciliación contra el Excel"),
])
pantallas.run()
