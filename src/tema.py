"""Colores de las pantallas, segun el tema (claro u oscuro) que usa el navegador."""
import streamlit as st

# Paleta categorica en orden fijo (azul, naranja, aqua, amarillo, magenta, verde).
# Validada con validate_palette.js en claro y oscuro: separacion para daltonismo y
# diferencia en vision normal OK. En claro, aqua/amarillo/magenta tienen poco contraste
# contra el fondo: por eso siempre van acompanados de leyenda, tooltip y tabla.
CATEGORICAS = {
    "claro": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
    "oscuro": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
}

# Pauta publica vs privada: dos entidades fijas. Violeta (publica) y aqua (privada) validados
# como par en claro y oscuro; no se reutilizan los azul/naranja de las dos primeras categorias.
PUBLICA_PRIVADA = {
    "claro": {"publica": "#6250d6", "privado": "#1baf7a"},
    "oscuro": {"publica": "#9085e9", "privado": "#199e70"},
}

SUPERFICIE ={"claro": "#ffffff", "oscuro": "#0e1117"}
ENCABEZADO = {"claro": "#f0f2f6", "oscuro": "#262730"}
BORDE = {"claro": "rgba(49,51,63,0.2)", "oscuro": "rgba(250,250,250,0.2)"}
TEXTO = {"claro": "#31333f", "oscuro": "#fafafa"}
TEXTO_SUAVE = {"claro": "#6b6e7a", "oscuro": "#a3a8b8"}


def modo() -> str:
    """'oscuro' o 'claro'. Si no se puede saber, claro."""
    try:
        return "oscuro" if st.context.theme.type == "dark" else "claro"
    except Exception:
        return "claro"
