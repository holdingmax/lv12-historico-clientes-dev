"""Pantalla "Clientes por mes". Solo lectura: no modifica la base."""
import html
from decimal import Decimal

import streamlit as st

from src import consultas, tema
from src.auth import require_login
from src.db import BaseNoConfigurada
from src.exportar import matriz_a_excel
from src.formato import MESES, MESES_CORTOS, md, normalizar_nombre, numero_ar, tabla_md
from src.matriz import armar_matriz

CERO = Decimal(0)
TIPOS_CLIENTE = {"Todos": None, "Privado": "privado", "Pública": "publica"}

# Fondos suaves con texto oscuro fijo: se leen igual en tema claro y oscuro.
COLOR_PERDIDO = ("#f8d7da", "#4a1414")
COLOR_NUEVO = ("#d4edda", "#143d1f")


def porcentaje(parte: Decimal, total: Decimal) -> str:
    return "-" if not total else f"{numero_ar(parte / total * 100, decimales=1)} %"


def tabla_html(matriz: dict, meses: list[int], duplicados: set[int]) -> str:
    """Matriz cliente x mes. Es HTML para poder colorear celdas, alinear y fijar el encabezado."""
    modo = tema.modo()
    borde, fondo_enc, superficie = tema.BORDE[modo], tema.ENCABEZADO[modo], tema.SUPERFICIE[modo]
    celda = f"padding:4px 10px;border-bottom:1px solid {borde};white-space:nowrap;"
    num = celda + "text-align:right;"
    # La primera columna queda fija al desplazar hacia los costados.
    nombre_col = celda + f"position:sticky;left:0;z-index:1;max-width:260px;overflow:hidden;text-overflow:ellipsis;background:{superficie};"
    total = matriz["total"]

    def th(texto, extra=""):
        return f"<th style='{num}position:sticky;top:0;z-index:2;background:{fondo_enc};{extra}'>{texto}</th>"

    # Total y Participación van justo después del nombre, para que se vean sin desplazarse.
    enc = (
        f"<th style='{celda}text-align:left;position:sticky;top:0;left:0;z-index:3;background:{fondo_enc};'>Cliente</th>"
        + th("Total") + th("Participación")
        + "".join(th(MESES_CORTOS[m - 1]) for m in meses)
    )
    cuerpo = []
    for c in matriz["clientes"]:
        icono = "⚠ " if c["id"] in duplicados else ""
        celdas = [f"<td style='{nombre_col}' title='{html.escape(c['nombre'], quote=True)}'>{icono}{html.escape(c['nombre'])}</td>"]
        celdas.append(f"<td style='{num}font-weight:600;'>{numero_ar(c['total'])}</td>")
        celdas.append(f"<td style='{num}'>{porcentaje(c['total'], total)}</td>")
        for m in meses:
            v = c["por_mes"].get(m)
            marca = c["marcas"].get(m)
            if marca == "perdido":
                fondo, texto = COLOR_PERDIDO
                celdas.append(f"<td style='{num}background:{fondo};color:{texto};'>▼ {numero_ar(v or CERO)}</td>")
            elif marca == "nuevo":
                fondo, texto = COLOR_NUEVO
                celdas.append(f"<td style='{num}background:{fondo};color:{texto};'>▲ {numero_ar(v)}</td>")
            elif v is None:
                celdas.append(f"<td style='{num}color:{tema.TEXTO_SUAVE[modo]};'>-</td>")
            else:
                celdas.append(f"<td style='{num}'>{numero_ar(v)}</td>")
        cuerpo.append("<tr>" + "".join(celdas) + "</tr>")

    def pie_td(texto, extra=""):
        return f"<td style='{num}position:sticky;bottom:0;background:{fondo_enc};{extra}'>{texto}</td>"

    pie = (
        f"<tr style='font-weight:700;'><td style='{celda}position:sticky;bottom:0;left:0;z-index:3;background:{fondo_enc};'>Total</td>"
        + pie_td(numero_ar(total)) + pie_td("100,0 %" if total else "-")
        + "".join(pie_td(numero_ar(matriz["totales_mes"][m])) for m in meses)
        + "</tr>"
    )
    return (
        f"<div style='max-height:640px;overflow:auto;border:1px solid {borde};border-radius:6px;'>"
        f"<table style='width:100%;border-collapse:collapse;font-size:0.9rem;color:{tema.TEXTO[modo]};'>"
        f"<thead><tr>{enc}</tr></thead><tbody>{''.join(cuerpo)}{pie}</tbody></table></div>"
    )


def leyenda() -> str:
    def ficha(color, texto):
        return (f"<span style='background:{color[0]};color:{color[1]};padding:2px 8px;"
                f"border-radius:4px;'>{texto}</span>")
    return (
        f"{ficha(COLOR_PERDIDO, '▼ Se perdió')} tuvo neto el mes anterior y este mes quedó en cero. &nbsp; "
        f"{ficha(COLOR_NUEVO, '▲ Nuevo')} aparece este mes y no había tenido neto antes en el año. &nbsp; "
        "⚠ posible cliente duplicado (ver aviso al pie)."
    )


def detalle_de_cliente(lote, anio, emisora_id, tipos_elegidos, matriz) -> None:
    nombres = {c["id"]: c["nombre"] for c in matriz["clientes"]}
    elegido = st.selectbox(
        "Ver detalle", [None] + list(nombres),
        format_func=lambda i: "Elegí un cliente…" if i is None else nombres[i],
    )
    if elegido is None:
        return
    lineas = consultas.lineas_de_cliente(lote, elegido, anio, emisora_id, tipos_elegidos)
    st.subheader(f"{nombres[elegido]} — {anio}")
    st.caption("Muestra las líneas con los mismos filtros de año, emisora y tipo de venta de arriba.")
    st.markdown(tabla_md(
        ["Mes", "Tipo de venta", "Agencia", "Emisora", "OP", "Neto"],
        [[MESES[l["mes"] - 1], md(l["tipo"]), md(l["agencia"]), md(l["emisora"]),
          md(l["op"]), numero_ar(l["neto"])] for l in lineas],
        derecha={5},
    ))
    st.markdown(f"**Total del cliente:** {numero_ar(sum((l['neto'] for l in lineas), CERO))}")


def main() -> None:
    require_login()  # primera linea: sin sesion no se consulta nada
    st.title("Clientes por mes")
    st.caption(
        "Neto de cada cliente mes a mes, según lo que quedó cargado en la base. "
        "Esta pantalla solo muestra datos: no modifica nada."
    )
    try:
        carga = consultas.ultima_carga()
        if carga is None:
            st.info("Todavía no se cargó ningún archivo.")
            return
        lote = carga["id"]
        anios = consultas.anios_con_datos(lote)
        if not anios:
            st.info("La última carga no tiene líneas.")
            return

        tipos = consultas.tipos_de_venta()
        nombres_tipo = {t["codigo"]: t["nombre"] for t in tipos}
        f1, f2, f3, f4 = st.columns([1, 2, 1.5, 2.5])
        anio = f1.selectbox("Año", anios)
        emisoras = {e["id"]: e["nombre"] for e in consultas.emisoras_con_datos(lote, anio)}
        emisora_id = f2.selectbox(
            "Emisora", [None] + list(emisoras), format_func=lambda i: "Todas" if i is None else emisoras[i]
        )
        tipo_cliente = TIPOS_CLIENTE[f3.selectbox("Tipo de cliente", list(TIPOS_CLIENTE))]
        busqueda = f4.text_input("Buscar cliente", placeholder="Parte del nombre")
        elegidos = st.multiselect(
            "Tipo de venta", list(nombres_tipo), default=list(nombres_tipo),
            format_func=lambda c: nombres_tipo[c],
        )
        if not elegidos:
            st.info("Elegí al menos un tipo de venta.")
            return

        meses = consultas.meses_con_datos(lote, anio)
        filas = consultas.neto_por_cliente_y_mes(
            lote, anio, emisora_id, elegidos, tipo_cliente, normalizar_nombre(busqueda)
        )
        if not filas:
            st.info("No hay clientes con esos filtros.")
            return
        matriz = armar_matriz(filas, meses)
        duplicados = consultas.clientes_con_sugerencia_abierta()

        st.markdown(f"**{numero_ar(len(matriz['clientes']), decimales=0)} clientes** · ordenados por total, de mayor a menor")
        st.markdown(leyenda(), unsafe_allow_html=True)
        st.markdown(tabla_html(matriz, meses, duplicados), unsafe_allow_html=True)

        # Control contra el Tablero: solo se puede comparar si no se filtra por cliente.
        if tipo_cliente is None and not busqueda.strip():
            tablero = consultas.neto_por_mes_y_tipo(lote, anio, emisora_id)
            total_tablero = sum((f["neto"] for f in tablero if f["tipo_venta"] in elegidos), CERO)
            if total_tablero == matriz["total"]:
                st.caption(f"Control: el total ({numero_ar(matriz['total'])}) coincide con el del Tablero mensual para los mismos filtros.")
            else:
                st.warning(
                    f"El total de esta tabla ({numero_ar(matriz['total'])}) no coincide con el del "
                    f"Tablero mensual ({numero_ar(total_tablero)}). Avisá al equipo."
                )

        st.download_button(
            "Descargar en Excel",
            data=matriz_a_excel(matriz, meses, duplicados, anio),
            file_name=f"clientes_por_mes_{anio}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        detalle_de_cliente(lote, anio, emisora_id, elegidos, matriz)

        n = consultas.cantidad_de_duplicados_posibles()
        if n:
            st.warning(
                f"Hay {n} posibles clientes duplicados sin resolver; los totales por cliente "
                "pueden estar partidos."
            )
    except BaseNoConfigurada as e:
        st.error(str(e))
    except Exception:
        # No se muestra el detalle tecnico: podria incluir datos de la conexion.
        st.error("No se pudo leer la base de datos. Probá de nuevo en un momento.")


main()
