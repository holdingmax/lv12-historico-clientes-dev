"""Tabla HTML simple para las pantallas: con desplazamiento horizontal si no entra."""
import html

from src import tema


def tabla_html(encabezados: list[str], filas: list[list[str]], derecha: set[int],
               ultima_en_negrita: bool = False) -> str:
    """Las celdas son texto plano (se escapan aca). Devuelve una sola linea de HTML."""
    modo = tema.modo()
    borde, fondo_enc = tema.BORDE[modo], tema.ENCABEZADO[modo]
    celda = f"padding:5px 8px;border-bottom:1px solid {borde};white-space:nowrap;"

    def estilo(i: int) -> str:
        return celda + ("text-align:right;" if i in derecha else "text-align:left;")

    enc = "".join(
        f"<th style='{estilo(i)}background:{fondo_enc};'>{html.escape(t)}</th>"
        for i, t in enumerate(encabezados)
    )
    cuerpo = []
    for n, fila in enumerate(filas):
        peso = "font-weight:700;" if ultima_en_negrita and n == len(filas) - 1 else ""
        cuerpo.append("<tr>" + "".join(
            f"<td style='{estilo(i)}{peso}'>{html.escape(c)}</td>" for i, c in enumerate(fila)
        ) + "</tr>")
    return (
        f"<div style='overflow-x:auto;border:1px solid {borde};border-radius:6px;'>"
        f"<table style='width:100%;border-collapse:collapse;font-size:0.85rem;color:{tema.TEXTO[modo]};'>"
        f"<thead><tr>{enc}</tr></thead><tbody>{''.join(cuerpo)}</tbody></table></div>"
    )
