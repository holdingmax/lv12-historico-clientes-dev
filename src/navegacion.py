"""Que pantallas ve cada rol en el menu. Sin Streamlit: se puede probar suelto."""

PANTALLAS_COMUNES = [
    {"archivo": "pantallas/tablero.py", "titulo": "Tablero mensual", "default": True},
    {"archivo": "pantallas/clientes_mes.py", "titulo": "Clientes por mes"},
    {"archivo": "pantallas/conciliacion.py", "titulo": "Conciliación contra el Excel"},
]
PANTALLAS_ADMIN = [
    {"archivo": "pantallas/fusion.py", "titulo": "Nombres duplicados"},
]


def paginas_para(usuario: dict) -> list[dict]:
    """El operador no ve las pantallas de administracion (ni existen para su sesion)."""
    paginas = list(PANTALLAS_COMUNES)
    if usuario["rol"] == "administrador":
        paginas += PANTALLAS_ADMIN
    return paginas
