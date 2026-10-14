import streamlit as st

from src.db import estado_base

st.set_page_config(page_title="LV12 - Historico de Clientes", layout="wide")
st.title("LV12 - Historico y evolucion de facturacion a clientes")
st.caption("Radio LV12. Proyecto en construccion.")

ok, mensaje = estado_base()
if ok:
    st.success(mensaje)
else:
    st.error(mensaje)

st.info(
    "Proximos pasos: modelo de datos, importacion del Resumen de Publicidades 2026 "
    "y conciliacion contra los archivos de la radio."
)
