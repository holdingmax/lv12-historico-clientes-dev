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


def variacion_porcentual(actual: Decimal, anterior: Decimal | None) -> Decimal | None:
    if anterior is None or anterior == 0:
        return None
    return (actual - anterior) / anterior * 100


def indicadores(meses, neto_mes, activos, anio) -> None:
    ultimo = meses[-1]
    anterior = ultimo - 1 if (ultimo - 1) in neto_mes else None
    variacion = variacion_porcentual(neto_mes[ultimo], neto_mes.get(anterior))
    acumulado = sum(neto_mes.values(), CERO)
    c1, c2, c3, c4 = st.columns(4)
    # En millones para que entre en la tarjeta; el importe exacto se ve al pasar el mouse.
    c1.metric(f"Neto de {MESES[ultimo - 1]}", f"$ {numero_ar(neto_mes[ultimo] / 1_000_000)} M",
              help=f"$ {numero_ar(neto_mes[ultimo])}")
    if variacion is None:
        c2.metric("Variación contra el mes anterior", "Sin dato")
    else:
        c2.metric(
            "Variación contra el mes anterior", f"{numero_ar(variacion, decimales=1)} %",
            delta=f"{numero_ar(variacion, con_signo=True, decimales=1)} % vs. {MESES[anterior - 1]}",
        )
    c3.metric(f"Acumulado {anio}", f"$ {numero_ar(acumulado / 1_000_000)} M",
              help=f"$ {numero_ar(acumulado)}")
    c4.metric(f"Clientes activos en {MESES[ultimo - 1]}", numero_ar(activos.get(ultimo, 0), decimales=0))


def grafico_apilado(meses, neto, tipos) -> None:
    modo = tema.modo()
    filas = [
        {"Mes": MESES_CORTOS[m - 1], "orden_mes": m, "Tipo de venta": t["nombre"],
         "orden_tipo": t["orden"], "Neto": float(neto.get((m, t["codigo"]), CERO)),
         "Neto en pesos": numero_ar(neto.get((m, t["codigo"]), CERO))}
        for m in meses for t in tipos
    ]
    df = pd.DataFrame(filas)
    superficie = tema.SUPERFICIE[modo]
    grafico = (
        alt.Chart(df)
        .mark_bar(size=24, stroke=superficie, strokeWidth=2)  # 2 px de aire entre segmentos
        .encode(
            x=alt.X("Mes:N", sort=[MESES_CORTOS[m - 1] for m in meses], title=None,
                    axis=alt.Axis(labelAngle=0, labelColor=tema.TEXTO_SUAVE[modo], domainColor=tema.BORDE[modo], ticks=False)),
            y=alt.Y("Neto:Q", title="Neto (millones de pesos)", stack="zero",
                    axis=alt.Axis(labelExpr="replace(format(datum.value / 1000000, '.1f'), '.', ',') + ' M'",
                                  labelColor=tema.TEXTO_SUAVE[modo], titleColor=tema.TEXTO_SUAVE[modo],
                                  gridColor=tema.BORDE[modo], domain=False)),
            color=alt.Color(
                "Tipo de venta:N",
                scale=alt.Scale(domain=[t["nombre"] for t in tipos], range=tema.CATEGORICAS[modo]),
                legend=alt.Legend(orient="bottom", title=None, labelColor=tema.TEXTO[modo]),
            ),
            order=alt.Order("orden_tipo:Q", sort="ascending"),
            tooltip=["Mes", "Tipo de venta", alt.Tooltip("Neto en pesos:N", title="Neto")],
        )
        .properties(height=380)
        .configure_view(stroke=None)
    )
    st.altair_chart(grafico, width="stretch")


def tabla_mes_tipo(meses, neto, iva, tipos, con_iva: bool) -> None:
    # El total va justo despues del mes para que se vea sin desplazar la tabla.
    encabezados = ["Mes", "Total"] + (["Total con IVA"] if con_iva else []) + [t["nombre"] for t in tipos]
    filas = []
    tot_tipo = {t["codigo"]: CERO for t in tipos}
    tot_iva = CERO
    for m in meses:
        fila_total = CERO
        por_tipo = []
        for t in tipos:
            v = neto.get((m, t["codigo"]))
            por_tipo.append("-" if v is None else numero_ar(v))
            if v is not None:
                fila_total += v
                tot_tipo[t["codigo"]] += v
        celdas = [MESES[m - 1], numero_ar(fila_total)]
        if con_iva:
            iva_mes = sum((iva.get((m, t["codigo"]), CERO) or CERO for t in tipos), CERO)
            tot_iva += iva_mes
            celdas.append(numero_ar(iva_mes))
        filas.append(celdas + por_tipo)
    fila_final = ["Total", numero_ar(sum(tot_tipo.values(), CERO))]
    if con_iva:
        fila_final.append(numero_ar(tot_iva))
    filas.append(fila_final + [numero_ar(tot_tipo[t["codigo"]]) for t in tipos])
    st.markdown(
        tabla_html(encabezados, filas, derecha=set(range(1, len(encabezados))), ultima_en_negrita=True),
        unsafe_allow_html=True,
    )


def main() -> None:
    require_login()  # primera linea: sin sesion no se consulta nada
    st.title("Tablero mensual")
    st.caption(
        "Neto facturado por mes y tipo de venta, según lo que quedó cargado en la base. "
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

        col_anio, col_emisora = st.columns(2)
        anio = col_anio.selectbox("Año", anios)  # el primero es el más reciente con datos
        emisoras = consultas.emisoras_con_datos(lote, anio)
        nombres = {e["id"]: e["nombre"] for e in emisoras}
        emisora_id = col_emisora.selectbox(
            "Emisora", [None] + list(nombres), format_func=lambda i: "Todas" if i is None else nombres[i]
        )

        tipos = consultas.tipos_de_venta()
        filas = consultas.neto_por_mes_y_tipo(lote, anio, emisora_id)
        if not filas:
            st.info("No hay datos para esa combinación de año y emisora.")
            return
        neto = {(f["mes"], f["tipo_venta"]): f["neto"] for f in filas}
        iva = {(f["mes"], f["tipo_venta"]): f["total_con_iva"] for f in filas}
        meses = sorted({f["mes"] for f in filas})  # los meses sin datos no aparecen
        neto_mes = {m: sum((v for (mm, _), v in neto.items() if mm == m), CERO) for m in meses}
        activos = consultas.clientes_activos_por_mes(lote, anio, emisora_id)

        indicadores(meses, neto_mes, activos, anio)
        st.subheader("Neto por mes y tipo de venta")
        grafico_apilado(meses, neto, tipos)
        st.subheader("Detalle por mes")
        con_iva = st.checkbox("Ver con IVA")
        tabla_mes_tipo(meses, neto, iva, tipos, con_iva)
        st.caption("Los meses sin datos no se muestran. “-” quiere decir que no hubo líneas de ese tipo en el mes.")
    except BaseNoConfigurada as e:
        st.error(str(e))
    except Exception:
        # No se muestra el detalle tecnico: podria incluir datos de la conexion.
        st.error("No se pudo leer la base de datos. Probá de nuevo en un momento.")


main()
