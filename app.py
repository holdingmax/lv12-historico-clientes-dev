import streamlit as st

st.set_page_config(page_title="LV12 - Historico de Clientes", layout="wide")

pantallas = st.navigation([
    st.Page("pantallas/conciliacion.py", title="Conciliación contra el Excel", default=True),
])
pantallas.run()
