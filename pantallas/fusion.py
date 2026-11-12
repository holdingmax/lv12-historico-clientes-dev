"""Pantalla "Nombres duplicados": unir clientes o agencias que son la misma entidad.
Solo administradores. Es la unica pantalla que escribe (a traves de src/fusion.py)."""
import streamlit as st

from src import consultas, fusion
from src.auth import require_admin
from src.db import BaseNoConfigurada
from src.formato import MESES_CORTOS, fecha_hora_ar, md, numero_ar, porcentaje_ar, tabla_md

CLAVE_PENDIENTE = "fusion_pendiente"   # union elegida, esperando confirmacion
CLAVE_AVISO = "fusion_aviso"           # mensaje de la ultima accion hecha
TEXTO_TIPO = {"publica": "pública", "privado": "privada"}


def periodos_texto(periodos: list[int]) -> str:
    """[202601, 202602] -> 'Ene, Feb' (con el año si hay mas de uno)."""
    if not periodos:
        return "ninguno"
    anios = {p // 100 for p in periodos}
    return ", ".join(
        MESES_CORTOS[p % 100 - 1] + (f" {p // 100}" if len(anios) > 1 else "") for p in sorted(periodos)
    )


def ficha(entidad: str, r: dict) -> str:
    texto = f"**{md(r['nombre'])}**  \nNeto total: {numero_ar(r['neto'])}  \nMeses: {periodos_texto(r['periodos'])}"
    if entidad == "cliente":
        texto += f"  \nTipo: {TEXTO_TIPO.get(r['tipo'], r['tipo'])}"
    return texto


def elegir_union(entidad: str, absorbido_id: int, sobreviviente_id: int) -> None:
    elegir_union_grupo(entidad, [absorbido_id], sobreviviente_id)


def elegir_union_grupo(entidad: str, absorbidos_ids: list[int], sobreviviente_id: int) -> None:
    st.session_state[CLAVE_PENDIENTE] = {
        "entidad": entidad, "absorbidos_ids": list(absorbidos_ids), "sobreviviente_id": sobreviviente_id,
    }
    st.rerun()


def panel_de_confirmacion(usuario: dict, lote: int) -> None:
    pendiente = st.session_state.get(CLAVE_PENDIENTE)
    if not pendiente:
        return
    entidad = pendiente["entidad"]
    resumen = {r["id"]: r for r in consultas.resumen_de_entidades(entidad, lote)}
    sobreviviente = resumen.get(pendiente["sobreviviente_id"])
    absorbidos = [resumen.get(i) for i in pendiente["absorbidos_ids"]]
    if sobreviviente is None or any(a is None for a in absorbidos):
        st.session_state.pop(CLAVE_PENDIENTE, None)
        st.warning("Uno de los nombres ya no existe (¿ya se unió?). Recargá la pantalla.")
        return
    distintos = entidad == "cliente" and any(a["tipo"] != sobreviviente["tipo"] for a in absorbidos)
    lineas = sum(a["lineas"] for a in absorbidos)
    nombres = ", ".join(f"«{md(a['nombre'])}»" for a in absorbidos)
    with st.container(border=True):
        st.subheader("Confirmá la unión")
        st.markdown(
            f"Se {'une' if len(absorbidos) == 1 else 'unen'} {nombres} dentro de **{md(sobreviviente['nombre'])}**. "
            f"Las {numero_ar(lineas, decimales=0)} líneas pasan a «{md(sobreviviente['nombre'])}» y "
            f"{'ese nombre queda' if len(absorbidos) == 1 else 'esos nombres quedan'} como alias: los próximos "
            f"archivos que {'lo traigan se cargan' if len(absorbidos) == 1 else 'los traigan se cargan'} directo en "
            f"«{md(sobreviviente['nombre'])}». **No se puede deshacer**, pero queda registrado."
        )
        if distintos:
            if len(absorbidos) == 1:
                a = absorbidos[0]
                quien = (f"«{a['nombre']}» es {TEXTO_TIPO[a['tipo']]} y "
                         f"«{sobreviviente['nombre']}» es {TEXTO_TIPO[sobreviviente['tipo']]}. ")
            else:
                quien = "Hay nombres de distinto tipo (pública y privada). "
            st.warning(
                f"Atención: {quien}Si unís, queda como pública (se conserva 'pública' si alguno lo era)."
            )
        col1, col2 = st.columns(2)
        if col1.button("Sí, unir", key="fusion_confirmar", type="primary"):
            try:
                if len(absorbidos) == 1:
                    r = fusion.unir(usuario, entidad, absorbidos[0]["id"], sobreviviente["id"],
                                    confirmar_tipo_distinto=distintos)
                    aviso = (f"Listo: «{r['absorbido']}» se unió a «{r['sobreviviente']}» "
                             f"({numero_ar(r['lineas_movidas'], decimales=0)} líneas).")
                else:
                    r = fusion.unir_grupo(usuario, entidad, sobreviviente["id"], [a["id"] for a in absorbidos],
                                          confirmar_tipo_distinto=distintos)
                    aviso = (f"Listo: {len(r['absorbidos'])} nombres se unieron a «{r['sobreviviente']}» "
                             f"({numero_ar(r['lineas_movidas'], decimales=0)} líneas).")
            except fusion.ErrorFusion as e:
                st.session_state.pop(CLAVE_PENDIENTE, None)
                st.error(str(e))
            else:
                st.session_state.pop(CLAVE_PENDIENTE, None)
                st.session_state[CLAVE_AVISO] = aviso
                st.rerun()
        if col2.button("Cancelar", key="fusion_cancelar"):
            st.session_state.pop(CLAVE_PENDIENTE, None)
            st.rerun()


def grupos_de_nombre_base(entidad: str, resumen: dict) -> None:
    """Variantes con parentesis de un nombre que existe solo ('Yuhmak', 'Yuhmak (Automoviles)'...)."""
    grupos = fusion.grupos_por_nombre_base(list(resumen.values()))
    if not grupos:
        return
    st.subheader("Mismo nombre con variantes entre paréntesis")
    st.caption("Parecen ser el mismo nombre con un aclaratorio. Unirlos deja el nombre sin paréntesis y las variantes como alias.")
    for g in grupos:
        base, variantes = g["base"], g["variantes"]
        with st.container(border=True):
            st.markdown(ficha(entidad, base))
            for v in variantes:
                st.markdown(f"+ {ficha(entidad, v)}")
            if st.button(f"Unir los {len(variantes) + 1} en «{base['nombre']}»", key=f"unir_grupo_{base['id']}"):
                elegir_union_grupo(entidad, [v["id"] for v in variantes], base["id"])


def pestana_sugerencias(usuario: dict, entidad: str, resumen: dict) -> None:
    grupos_de_nombre_base(entidad, resumen)
    sugerencias = consultas.sugerencias_con_ids(entidad)
    if not sugerencias:
        st.success("No hay otras sugerencias abiertas.")
        return
    st.write(f"{len(sugerencias)} {'sugerencia' if len(sugerencias) == 1 else 'sugerencias'} para revisar, de mayor a menor parecido.")
    for s in sugerencias:
        nuevo, parecido = resumen.get(s["nombre_id"]), resumen.get(s["parecido_id"])
        if nuevo is None or parecido is None:
            continue
        with st.container(border=True):
            st.markdown(f"Parecido: **{porcentaje_ar(s['similitud'])}**")
            col1, col2 = st.columns(2)
            col1.markdown(ficha(entidad, nuevo))
            col2.markdown(ficha(entidad, parecido))
            b1, b2, b3 = st.columns(3)
            if b1.button(f"Unir: queda «{nuevo['nombre']}»", key=f"unir_{s['id']}_nuevo"):
                elegir_union(entidad, parecido["id"], nuevo["id"])
            if b2.button(f"Unir: queda «{parecido['nombre']}»", key=f"unir_{s['id']}_parecido"):
                elegir_union(entidad, nuevo["id"], parecido["id"])
            if b3.button("No es el mismo", key=f"descartar_{s['id']}"):
                try:
                    fusion.descartar_sugerencia(usuario, s["id"])
                except fusion.ErrorFusion as e:
                    st.error(str(e))
                else:
                    st.session_state[CLAVE_AVISO] = f"Listo: «{nuevo['nombre']}» y «{parecido['nombre']}» quedan como distintos."
                    st.rerun()


def pestana_manual(entidad: str, resumen: dict) -> None:
    st.write(
        "Elegí dos nombres para unirlos aunque no tengan sugerencia. "
        "Podés escribir en cada lista para buscar."
    )
    ids = list(resumen)  # ya vienen ordenados por nombre
    opciones = [None] + ids
    nombre = lambda i: "Elegí un nombre…" if i is None else resumen[i]["nombre"]
    col1, col2 = st.columns(2)
    a = col1.selectbox("Primer nombre", opciones, format_func=nombre, key=f"fusion_a_{entidad}")
    b = col2.selectbox("Segundo nombre", opciones, format_func=nombre, key=f"fusion_b_{entidad}")
    if a is None or b is None:
        return
    if a == b:
        st.warning("Elegiste el mismo nombre dos veces.")
        return
    col1.markdown(ficha(entidad, resumen[a]))
    col2.markdown(ficha(entidad, resumen[b]))
    queda = st.radio("¿Cuál nombre queda?", [a, b], format_func=lambda i: resumen[i]["nombre"],
                     horizontal=True, key=f"fusion_queda_{entidad}")
    if st.button("Unir…", key=f"fusion_manual_unir_{entidad}"):
        elegir_union(entidad, b if queda == a else a, queda)


def pestana_historial() -> None:
    filas = consultas.uniones_hechas()
    if not filas:
        st.write("Todavía no se unió ningún nombre.")
        return
    st.markdown(tabla_md(
        ["Fecha", "Es", "Se unió", "A", "Líneas", "Quién"],
        [[fecha_hora_ar(f["fecha"]), "Cliente" if f["entidad"] == "cliente" else "Agencia",
          md(f["absorbido_nombre"]), md(f["sobreviviente_nombre"]),
          numero_ar(f["lineas_movidas"], decimales=0), md(f["usuario_email"])] for f in filas],
        derecha={4},
    ))


def main() -> None:
    usuario = require_admin()  # primera linea: sin sesion de administrador no se consulta nada
    st.title("Nombres duplicados")
    st.caption(
        "Unir clientes o agencias que son la misma entidad con nombres distintos. "
        "Solo para administradores. Unir no se puede deshacer, pero queda registrado."
    )
    try:
        carga = consultas.ultima_carga()
        if carga is None:
            st.info("Todavía no se cargó ningún archivo.")
            return
        aviso = st.session_state.pop(CLAVE_AVISO, None)
        if aviso:
            st.success(aviso)
        panel_de_confirmacion(usuario, carga["id"])

        entidad = {"Clientes": "cliente", "Agencias": "agencia"}[
            st.radio("Qué querés revisar", ["Clientes", "Agencias"], horizontal=True, key="fusion_entidad")
        ]
        resumen = {r["id"]: r for r in consultas.resumen_de_entidades(entidad, carga["id"])}
        tab_sug, tab_manual, tab_hist = st.tabs(["Sugerencias", "Unir manualmente", "Uniones hechas"])
        with tab_sug:
            pestana_sugerencias(usuario, entidad, resumen)
        with tab_manual:
            pestana_manual(entidad, resumen)
        with tab_hist:
            pestana_historial()
    except BaseNoConfigurada as e:
        st.error(str(e))
    except Exception:
        # No se muestra el detalle tecnico: podria incluir datos de la conexion.
        st.error("No se pudo completar la operación. Probá de nuevo en un momento.")


main()
