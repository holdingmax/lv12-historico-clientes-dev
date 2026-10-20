"""Formato de numeros, fechas y tablas para las pantallas (convenciones argentinas)."""
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
ZONA = ZoneInfo("America/Argentina/Tucuman")


def numero_ar(x, con_signo: bool = False, decimales: int = 2) -> str:
    """1234567.8 -> '1.234.567,80'. Con con_signo, los positivos llevan '+'."""
    if x is None:
        return "-"
    texto = f"{Decimal(x):,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if con_signo and Decimal(x) > 0:
        texto = "+" + texto
    return texto


def porcentaje_ar(similitud) -> str:
    """0.957 -> '95,7 %'."""
    return f"{numero_ar(Decimal(similitud) * 100, decimales=1)} %"


def fecha_hora_ar(fecha: datetime) -> str:
    return fecha.astimezone(ZONA).strftime("%d/%m/%Y %H:%M")


def mes_anio(anio: int, mes: int) -> str:
    return f"{MESES[mes - 1]} {anio}"


def md(texto) -> str:
    """Escapa un texto para que no se interprete como formato dentro de una tabla markdown."""
    if texto is None or str(texto).strip() == "":
        return "-"
    return re.sub(r"([\\`*_{}\[\]<>|$~#:])", r"\\\1", str(texto)).replace("\n", " ")


def tabla_md(encabezados: list[str], filas: list[list[str]], derecha: set[int] = frozenset()) -> str:
    """Tabla markdown. Las celdas ya vienen escapadas/formateadas. `derecha`: columnas alineadas a la derecha."""
    sep = ["---:" if i in derecha else ":---" for i in range(len(encabezados))]
    lineas = ["| " + " | ".join(encabezados) + " |", "| " + " | ".join(sep) + " |"]
    lineas += ["| " + " | ".join(f) + " |" for f in filas]
    return "\n".join(lineas)
