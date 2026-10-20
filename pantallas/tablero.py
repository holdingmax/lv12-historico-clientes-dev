"""Pantalla "Tablero mensual". Solo lectura: no modifica la base."""
from decimal import Decimal

import altair as alt
import pandas as pd
import streamlit as st

from src import consultas, tema
from src.auth import require_login
from src.db import BaseNoConfigurada
from src.formato import MESES, MESES_CORTOS, numero_ar
from src.tablas import tabla_html

CERO = Decimal(0)
VER_POR_TIPO = "Tipo de venta"
VER_POR_CLASE = "Pública vs Privada"


def variacion_porcentual(actual: Decimal, anterior: Decimal | None) -> Decimal | None:
    if anterior is None or anterior == 0:
        return None
    return (actual - anterior) / anterior * 100


def participacion(parte: Decimal, total: Decimal) -> Decimal | None:
    return None if not total else parte / total * 100


def indicadores(meses, neto_mes, activos, anio, publica_ultimo: Decimal) -> None:
    ultimo = meses[-1]
    anterior = ultimo - 1 if (ultimo - 1) in neto_mes else None
    variacion = variacion_porcentual(neto_mes[ultimo], neto_mes.get(anterior))
    acumulado = sum(neto_mes.values(), CERO)
    pct_publica = participacion(publica_ultimo, neto_mes[ultimo])
    c1, c2, c3, c4, c5 = st.columns(5)
    # En millones para que entre en la tarjeta; el importe exacto se ve al pasar el mouse.
    c1.metric(f"Neto de {MESES[ultimo - 1]}", f"$ {numero_ar(neto_mes[ultimo] / 1_000_000)} M",
              help=f"$ {numero_ar(neto_mes[ultimo])}")
    if variacion is None:
        c2.metric("Variación mensual", "Sin dato")
    else:
        c2.metric(
            "Variación mensual", f"{numero_ar(variacion, decimales=1)} %",
            delta=f"{numero_ar(variacion, con_signo=True, decimales=1)} % vs. {MESES[anterior - 1]}",
        )
    c3.metric(f"Acumulado {anio}", f"$ {numero_ar(acumulado / 1_000_000)} M",
              help=f"$ {numero_ar(acumulado)}")
    c4.metric(f"Clientes activos ({MESES_CORTOS[ultimo - 1]})", numero_ar(activos.get(ultimo, 0), decimales=0),
              help=f"Clientes con neto mayor a cero en {MESES[ultimo - 1]}")
    c5.metric(
        f"Pauta pública ({MESES_CORTOS[ultimo - 1]})",
        "Sin dato" if pct_publica is None else f"{numero_ar(pct_publica, decimales=1)} %",
        help=f"$ {numero_ar(publica_ultimo)} del neto del mes",
    )


def categorias_por_tipo(tipos) -> list[dict]:
    colores = tema.CATEGORICAS[tema.modo()]
    return [
        {"clave": t["codigo"], "nombre": t["nombre"], "color": colores[i], "orden_grafico": t["orden"]}
        for i, t in enumerate(tipos)
    ]


def categorias_por_clase() -> list[dict]:
    colores = tema.PUBLICA_PRIVADA[tema.modo()]
    # En la tabla va primero Pública; en el grafico la privada (la mas grande) queda abajo.
    return [
        {"clave": "publica", "nombre": "Pública", "color": colores["publica"], "orden_grafico": 2},
        {"clave": "privado", "nombre": "Privada", "color": colores["privado"], "orden_grafico": 1},
    ]


def grafico_apilado(meses, neto, categorias, titulo_leyenda: str) -> None:
    modo = tema.modo()
    filas = [
        {"Mes": MESES_CORTOS[m - 1], titulo_leyenda: c["nombre"], "orden": c["orden_grafico"],
         "Neto": float(neto.get((m, c["clave"]), CERO)),
         "Neto en pesos": numero_ar(neto.get((m, c["clave"]), CERO))}
        for m in meses for c in categorias
    ]
    df = pd.DataFrame(filas)
    grafico = (
        alt.Chart(df)
        .mark_bar(size=24, stroke=tema.SUPERFICIE[modo], strokeWidth=2)  # 2 px de aire entre segmentos
        .encode(
            x=alt.X("Mes:N", sort=[MESES_CORTOS[m - 1] for m in meses], title=None,
                    axis=alt.Axis(labelAngle=0, labelColor=tema.TEXTO_SUAVE[modo], domainColor=tema.BORDE[modo], ticks=False)),
            y=alt.Y("Neto:Q", title="Neto (millones de pesos)", stack="zero",
                    axis=alt.Axis(labelExpr="replace(format(datum.value / 1000000, '.1f'), '.', ',') + ' M'",
                                  labelColor=tema.TEXTO_SUAVE[modo], titleColor=tema.TEXTO_SUAVE[modo],
                                  gridColor=tema.BORDE[modo], domain=False)),
            color=alt.Color(
                f"{titulo_leyenda}:N",
                scale=alt.Scale(domain=[c["nombre"] for c in categorias], range=[c["color"] for c in categorias]),
                legend=alt.Legend(orient="bottom", title=None, labelColor=tema.TEXTO[modo]),
            ),
            order=alt.Order("orden:Q", sort="ascending"),
            tooltip=["Mes", titulo_leyenda, alt.Tooltip("Neto en pesos:N", title="Neto")],
        )
        .properties(height=380)
        .configure_view(stroke=None)
    )
    st.altair_chart(grafico, width="stretch")


def tabla_mes(meses, neto, iva, categorias, con_iva: bool, con_participacion_publica: bool) -> None:
    # El total va justo despues del mes para que se vea sin desplazar la tabla.
    encabezados = ["Mes", "Total"] + (["Total con IVA"] if con_iva else []) + [c["nombre"] for c in categorias]
    if con_participacion_publica:
        encabezados.append("% Pública")
    filas = []
    tot_cat = {c["clave"]: CERO for c in categorias}
    tot_iva = CERO
    for m in meses:
        fila_total = CERO
        por_cat = []
        for c in categorias:
            v = neto.get((m, c["clave"]))
            por_cat.append("-" if v is None else numero_ar(v))
            if v is not None:
                fila_total += v
                tot_cat[c["clave"]] += v
        celdas = [MESES[m - 1], numero_ar(fila_total)]
        if con_iva:
            iva_mes = sum((iva.get((m, c["clave"]), CERO) or CERO for c in categorias), CERO)
            tot_iva += iva_mes
            celdas.append(numero_ar(iva_mes))
        extra = []
        if con_participacion_publica:
            p = participacion(neto.get((m, "publica"), CERO), fila_total)
            extra.append("-" if p is None else f"{numero_ar(p, decimales=1)} %")
        filas.append(celdas + por_cat + extra)
    total_general = sum(tot_cat.values(), CERO)
    fila_final = ["Total", numero_ar(total_general)]
    if con_iva:
        fila_final.append(numero_ar(tot_iva))
    fila_final += [numero_ar(tot_cat[c["clave"]]) for c in categorias]
    if con_participacion_publica:
        p = participacion(tot_cat["publica"], total_general)
        fila_final.append("-" if p is None else f"{numero_ar(p, decimales=1)} %")
    filas.append(fila_final)
    st.markdown(
        tabla_html(encabezados, filas, derecha=set(range(1, len(encabezados))), ultima_en_negrita=True),
        unsafe_allow_html=True,
    )


def main() -> None:
    require_login()  # primera linea: sin sesion no se consulta nada
    st.title("Tablero mensual")
    st.caption(
        "Neto facturado por mes, según lo que quedó cargado en la base. "
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

        col_anio, col_emisora, col_ver = st.columns([1, 2, 2])
        anio = col_anio.selectbox("Año", anios)  # el primero es el más reciente con datos
        emisoras = consultas.emisoras_con_datos(lote, anio)
        nombres = {e["id"]: e["nombre"] for e in emisoras}
        emisora_id = col_emisora.selectbox(
            "Emisora", [None] + list(nombres), format_func=lambda i: "Todas" if i is None else nombres[i]
        )
        ver_por = col_ver.radio("Ver por", [VER_POR_TIPO, VER_POR_CLASE], horizontal=True)

        tipos = consultas.tipos_de_venta()
        filas_tipo = consultas.neto_por_mes_y_tipo(lote, anio, emisora_id)
        if not filas_tipo:
            st.info("No hay datos para esa combinación de año y emisora.")
            return
        filas_clase = consultas.neto_por_mes_y_clase(lote, anio, emisora_id)
        neto_tipo = {(f["mes"], f["tipo_venta"]): f["neto"] for f in filas_tipo}
        iva_tipo = {(f["mes"], f["tipo_venta"]): f["total_con_iva"] for f in filas_tipo}
        neto_clase = {(f["mes"], f["tipo"]): f["neto"] for f in filas_clase}
        iva_clase = {(f["mes"], f["tipo"]): f["total_con_iva"] for f in filas_clase}
        meses = sorted({f["mes"] for f in filas_tipo})  # los meses sin datos no aparecen
        neto_mes = {m: sum((v for (mm, _), v in neto_tipo.items() if mm == m), CERO) for m in meses}
        activos = consultas.clientes_activos_por_mes(lote, anio, emisora_id)

        indicadores(meses, neto_mes, activos, anio, neto_clase.get((meses[-1], "publica"), CERO))

        if ver_por == VER_POR_CLASE:
            categorias, neto, iva, leyenda = categorias_por_clase(), neto_clase, iva_clase, "Pauta"
            st.subheader("Neto por mes: pública y privada")
        else:
            categorias, neto, iva, leyenda = categorias_por_tipo(tipos), neto_tipo, iva_tipo, "Tipo de venta"
            st.subheader("Neto por mes y tipo de venta")
        grafico_apilado(meses, neto, categorias, leyenda)
        st.subheader("Detalle por mes")
        con_iva = st.checkbox("Ver con IVA")
        tabla_mes(meses, neto, iva, categorias, con_iva, con_participacion_publica=(ver_por == VER_POR_CLASE))
        st.caption("Los meses sin datos no se muestran. “-” quiere decir que no hubo líneas de ese tipo en el mes.")
    except BaseNoConfigurada as e:
        st.error(str(e))
    except Exception:
        # No se muestra el detalle tecnico: podria incluir datos de la conexion.
        st.error("No se pudo leer la base de datos. Probá de nuevo en un momento.")


main()
