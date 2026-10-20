"""Pantalla "Conciliación contra el Excel". Solo lectura: no modifica la base."""
from decimal import Decimal

import streamlit as st

from src import consultas
from src.db import BaseNoConfigurada
from src.formato import (
    fecha_hora_ar, md, mes_anio, numero_ar, porcentaje_ar, tabla_md,
)

TOLERANCIA = Decimal("0.005")  # por redondeo a centavos


def color(valor_formateado: str, dif: Decimal | None) -> str:
    """Rojo si hay diferencia, verde si no. El signo (+/-) acompaña al color."""
    if dif is None:
        return valor_formateado
    return f":green[{valor_formateado}]" if dif == 0 else f":red[{valor_formateado}]"


def tabla_conciliacion(filas: list[dict]) -> str:
    cuerpo, tot_base, tot_excel = [], Decimal(0), Decimal(0)
    for f in filas:
        base, excel = f["neto_base"], f["neto_excel"]
        dif = None if excel is None else base - excel
        tot_base += base
        tot_excel += excel or 0
        cuerpo.append([
            md(f["nombre"]), numero_ar(base), numero_ar(excel),
            color(numero_ar(dif, con_signo=True), dif),
        ])
    dif_total = tot_base - tot_excel
    cuerpo.append([
        "**Total**", f"**{numero_ar(tot_base)}**", f"**{numero_ar(tot_excel)}**",
        f"**{color(numero_ar(dif_total, con_signo=True), dif_total)}**",
    ])
    return tabla_md(
        ["Tipo de venta", "Neto en la base", "Neto en el Excel", "Diferencia"], cuerpo, derecha={1, 2, 3}
    )


def detalle_de_diferencia(lote: int, anio: int, mes: int, f: dict) -> None:
    base, excel = f["neto_base"], f["neto_excel"]
    dif = base - excel
    st.subheader(f"{f['nombre']} — {mes_anio(anio, mes)}")
    sentido = "de más en la base" if dif > 0 else "de menos en la base"
    st.write(
        f"Las líneas cargadas suman {numero_ar(base)} y el total del Excel dice "
        f"{numero_ar(excel)}: hay {numero_ar(abs(dif))} {sentido}."
    )
    lineas = consultas.lineas_del_tipo(lote, anio, mes, f["codigo"])
    coinciden = [l for l in lineas if abs(l["neto"] - dif) < TOLERANCIA] if dif > 0 else []
    if coinciden:
        nombres = ", ".join(f"{l['cliente']} (fila {l['fila']})" for l in coinciden)
        st.info(
            f"Para empezar a revisar: {'la línea' if len(coinciden) == 1 else 'las líneas'} "
            f"{nombres} {'tiene' if len(coinciden) == 1 else 'tienen'} el mismo importe que la "
            f"diferencia. Puede que el total del Excel no la esté sumando."
        )
    ids = {id(l) for l in coinciden}
    filas = [[
        md(l["cliente"]), md(l["agencia"]), md(l["periodo"]), md(l["emisora"]),
        numero_ar(l["neto"]), str(l["fila"]),
        "**◄ Mismo importe que la diferencia**" if id(l) in ids else "",
    ] for l in lineas]
    st.markdown(
        tabla_md(["Cliente", "Agencia", "Período", "Emisora", "Neto", "Fila en el Excel", ""],
                 filas, derecha={4, 5})
    )


def resumen_ultima_carga(carga: dict) -> None:
    st.subheader("Última carga")
    st.markdown(
        f"- **Archivo:** {md(carga['archivo'])}\n"
        f"- **Fecha:** {fecha_hora_ar(carga['fecha'])}\n"
        f"- **Líneas cargadas:** {numero_ar(carga['filas_ok'], decimales=0)}\n"
        f"- **Líneas rechazadas:** {numero_ar(carga['filas_rechazadas'], decimales=0)}"
    )
    if carga["filas_rechazadas"]:
        st.warning("Hay líneas del Excel que no se cargaron. Conviene revisarlas.")


def para_consultar_con_maxi(carga: dict) -> None:
    st.header("Para consultar con Maxi")
    lote = carga["id"]

    st.subheader("Diferencias contra el Excel")
    difs = consultas.diferencias_de_la_carga(lote)
    if not difs:
        st.write("Ninguna: todos los totales coinciden.")
    for d in difs:
        dif = d["neto_base"] - d["neto_excel"]
        texto = (
            f"**{mes_anio(d['anio'], d['mes'])} — {d['nombre']}:** las líneas suman "
            f"{numero_ar(d['neto_base'])} y el total del Excel dice {numero_ar(d['neto_excel'])} "
            f"(diferencia de {numero_ar(abs(dif))})."
        )
        if dif > 0:
            lineas = consultas.lineas_del_tipo(lote, d["anio"], d["mes"], d["codigo"])
            coinciden = [l for l in lineas if abs(l["neto"] - dif) < TOLERANCIA]
            if coinciden:
                l = coinciden[0]
                texto += (
                    f" La línea con ese importe es {md(l['cliente'])} (fila {l['fila']} de la "
                    f"hoja {l['hoja']}). ¿El total del Excel debería sumarla?"
                )
        st.markdown(texto)

    codigos = consultas.lineas_con_codigo_de_op(lote)
    st.subheader(f"Códigos de OP en la columna Vendedor ({len(codigos)})")
    st.write(
        "En estas líneas, la columna Vendedor del Excel trae un número que parece un código "
        "de OP. Se guardaron tal cual. ¿Es un vendedor o un número de orden?"
    )
    st.markdown(tabla_md(
        ["Mes", "Cliente", "Período", "Emisora", "Neto", "Lo que dice Vendedor", "Fila en el Excel"],
        [[mes_anio(c["anio"], c["mes"]), md(c["cliente"]), md(c["periodo"]), md(c["emisora"]),
          numero_ar(c["neto"]), md(c["vendedor"]), str(c["fila"])] for c in codigos],
        derecha={4, 6},
    ))

    sugerencias = consultas.sugerencias_abiertas()
    st.subheader(f"Nombres que se parecen ({len(sugerencias)})")
    st.write(
        "Estos nombres se cargaron como clientes o agencias distintos, pero se parecen mucho a "
        "otro ya existente. ¿Son el mismo? Todavía no se pueden unir desde esta pantalla: por "
        "ahora es solo para revisarlos."
    )
    st.markdown(tabla_md(
        ["Es", "Nombre cargado", "Se parece a", "Parecido"],
        [["Cliente" if s["entidad"] == "cliente" else "Agencia", md(s["nombre"]),
          md(s["parecido"]), porcentaje_ar(s["similitud"])] for s in sugerencias],
        derecha={3},
    ))


def main() -> None:
    st.title("Conciliación contra el Excel")
    st.caption(
        "Compara lo que quedó cargado en la base con los totales que trae el Excel. "
        "Esta pantalla solo muestra datos: no modifica nada."
    )

    try:
        carga = consultas.ultima_carga()
        if carga is None:
            st.info("Todavía no se cargó ningún archivo.")
            return
        lote = carga["id"]
        meses = consultas.meses_de_la_carga(lote)
        con_diferencia = {(d["anio"], d["mes"]) for d in consultas.diferencias_de_la_carga(lote)}
        # Se abre en el primer mes con diferencias; si no hay, en el último.
        inicial = next((m for m in meses if m in con_diferencia), meses[-1])
        anio, mes = st.selectbox(
            "Mes", meses, index=meses.index(inicial), format_func=lambda m: mes_anio(*m)
        )

        filas = consultas.conciliacion_del_mes(lote, anio, mes)
        st.markdown(tabla_conciliacion(filas))
        con_dif = [f for f in filas if f["neto_excel"] is not None and f["neto_base"] != f["neto_excel"]]
        if con_dif:
            st.error(
                f"En {mes_anio(anio, mes)} hay diferencias en {len(con_dif)} "
                f"{'tipo' if len(con_dif) == 1 else 'tipos'} de venta. Abajo se ven las líneas para revisarlas."
            )
        else:
            st.success(f"En {mes_anio(anio, mes)} todos los totales coinciden con el Excel.")

        if con_dif:
            st.header("Detalle de las líneas con diferencia")
            for f in con_dif:
                detalle_de_diferencia(lote, anio, mes, f)

        resumen_ultima_carga(carga)
        para_consultar_con_maxi(carga)
    except BaseNoConfigurada as e:
        st.error(str(e))
    except Exception:
        # No se muestra el detalle tecnico: podria incluir datos de la conexion.
        st.error("No se pudo leer la base de datos. Probá de nuevo en un momento.")


main()
