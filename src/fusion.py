"""Union de nombres duplicados (clientes o agencias). Solo administradores.

Es la UNICA escritura de esta pantalla y pasa por `_conexion_escritura`, privada de este modulo
(las demas pantallas siguen en solo lectura). Unir es irreversible: la fila absorbida se borra,
asi que todo ocurre en una sola transaccion y queda registrado en fusion_log.
El rol de administrador se verifica contra la base en cada operacion, no solo en la sesion.
"""
import os
import re

import psycopg
import streamlit as st
from psycopg.rows import dict_row

from src.db import BaseNoConfigurada
from src.formato import normalizar_nombre

# entidad -> (tabla, tabla de alias, columna que la referencia). Son constantes: el nombre de
# tabla nunca viene del usuario (se valida la entidad contra este diccionario).
ENTIDADES = {
    "cliente": ("cliente", "cliente_alias", "cliente_id"),
    "agencia": ("agencia", "agencia_alias", "agencia_id"),
}
MENSAJE_SOLO_ADMIN = "Esta acción es solo para administradores."


class ErrorFusion(Exception):
    """Error que se le puede mostrar tal cual a la persona (sin datos tecnicos)."""

    def __init__(self, mensaje: str, requiere_confirmacion: bool = False):
        super().__init__(mensaje)
        self.requiere_confirmacion = requiere_confirmacion


def _conexion_escritura() -> psycopg.Connection:
    """Conexion con permiso de escritura. Privada de este modulo: usar como `with`."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise BaseNoConfigurada(
            "Falta configurar la conexion a la base de datos (variable DATABASE_URL)."
        )
    return psycopg.connect(url, row_factory=dict_row)


def _exigir_admin(conn, usuario: dict) -> dict:
    fila = conn.execute(
        "SELECT id, email, rol, activo FROM usuario WHERE id = %s", (usuario.get("id"),)
    ).fetchone()
    if fila is None or not fila["activo"] or fila["rol"] != "administrador":
        raise ErrorFusion(MENSAJE_SOLO_ADMIN)
    return fila


def _suma_de_netos(conn):
    return conn.execute("SELECT coalesce(sum(neto), 0) AS total FROM orden_linea").fetchone()["total"]


def _repuntar_sugerencias(conn, entidad: str, absorbido_id: int, sobreviviente_id: int) -> None:
    """La sugerencia entre los dos queda 'fusionada'; las demas que tocaban al absorbido pasan al
    sobreviviente (si ya hay una igual, se borra la repetida). Los ids no tienen clave foranea."""
    filas = conn.execute(
        "SELECT id, nombre_id, parecido_id FROM sugerencia_fusion "
        "WHERE entidad = %s AND (nombre_id = %s OR parecido_id = %s) ORDER BY id FOR UPDATE",
        (entidad, absorbido_id, absorbido_id),
    ).fetchall()
    for f in filas:
        otro = f["parecido_id"] if f["nombre_id"] == absorbido_id else f["nombre_id"]
        if otro == sobreviviente_id:
            conn.execute("UPDATE sugerencia_fusion SET estado = 'fusionada' WHERE id = %s", (f["id"],))
            continue
        nuevo, parecido = (sobreviviente_id, otro) if f["nombre_id"] == absorbido_id else (otro, sobreviviente_id)
        repetida = conn.execute(
            "SELECT 1 FROM sugerencia_fusion WHERE entidad = %s AND id <> %s AND "
            "((nombre_id = %s AND parecido_id = %s) OR (nombre_id = %s AND parecido_id = %s))",
            (entidad, f["id"], nuevo, parecido, parecido, nuevo),
        ).fetchone()
        if repetida:
            conn.execute("DELETE FROM sugerencia_fusion WHERE id = %s", (f["id"],))
        else:
            conn.execute(
                "UPDATE sugerencia_fusion SET nombre_id = %s, parecido_id = %s WHERE id = %s",
                (nuevo, parecido, f["id"]),
            )


def _registrar_en_el_log(conn, entidad, absorbido, sobreviviente, movidas, admin) -> None:
    conn.execute(
        "INSERT INTO fusion_log (entidad, absorbido_id, absorbido_nombre, sobreviviente_id, "
        "sobreviviente_nombre, lineas_movidas, usuario_id, usuario_email) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (entidad, absorbido["id"], absorbido["nombre"], sobreviviente["id"], sobreviviente["nombre"],
         movidas, admin["id"], admin["email"]),
    )


def _unir_en(conn, usuario: dict, entidad: str, absorbido_id: int, sobreviviente_id: int,
             confirmar_tipo_distinto: bool = False) -> dict:
    """Nucleo de la union sobre una conexion ya abierta (el commit lo decide quien llama)."""
    if entidad not in ENTIDADES:
        raise ErrorFusion("Entidad desconocida.")
    if absorbido_id == sobreviviente_id:
        raise ErrorFusion("Elegí dos nombres distintos.")
    tabla, tabla_alias, col = ENTIDADES[entidad]
    admin = _exigir_admin(conn, usuario)

    columnas = "id, nombre, tipo" if entidad == "cliente" else "id, nombre"
    filas = conn.execute(  # se bloquean en orden de id para no cruzarse con otra union
        f"SELECT {columnas} FROM {tabla} WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
        (absorbido_id, sobreviviente_id),
    ).fetchall()
    if len(filas) != 2:
        raise ErrorFusion("Uno de los dos nombres ya no existe (¿ya se unió?). Recargá la pantalla.")
    por_id = {f["id"]: f for f in filas}
    absorbido, sobreviviente = por_id[absorbido_id], por_id[sobreviviente_id]

    tipo_final = None
    if entidad == "cliente":
        if absorbido["tipo"] != sobreviviente["tipo"] and not confirmar_tipo_distinto:
            raise ErrorFusion(
                "Uno es pública y el otro privada: hace falta confirmar la unión.",
                requiere_confirmacion=True,
            )
        # Regla: si alguno era pauta publica, el resultado conserva 'publica'.
        tipo_final = "publica" if "publica" in (absorbido["tipo"], sobreviviente["tipo"]) else sobreviviente["tipo"]

    antes = _suma_de_netos(conn)
    movidas = conn.execute(
        f"UPDATE orden_linea SET {col} = %s WHERE {col} = %s", (sobreviviente_id, absorbido_id)
    ).rowcount
    # Todos los alias del absorbido pasan al sobreviviente; y por si faltara, su propio nombre tambien.
    conn.execute(f"UPDATE {tabla_alias} SET {col} = %s WHERE {col} = %s", (sobreviviente_id, absorbido_id))
    conn.execute(
        f"INSERT INTO {tabla_alias} (alias_normalizado, {col}) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (normalizar_nombre(absorbido["nombre"]), sobreviviente_id),
    )
    if entidad == "cliente":
        conn.execute("UPDATE alerta SET cliente_id = %s WHERE cliente_id = %s", (sobreviviente_id, absorbido_id))
        if tipo_final != sobreviviente["tipo"]:
            conn.execute("UPDATE cliente SET tipo = %s WHERE id = %s", (tipo_final, sobreviviente_id))
    _repuntar_sugerencias(conn, entidad, absorbido_id, sobreviviente_id)
    _registrar_en_el_log(conn, entidad, absorbido, sobreviviente, movidas, admin)
    conn.execute(f"DELETE FROM {tabla} WHERE id = %s", (absorbido_id,))

    despues = _suma_de_netos(conn)
    if antes != despues:  # no deberia pasar nunca; si pasa, no se une nada
        raise ErrorFusion("La suma de los importes cambió durante la unión: no se unió nada.")
    return {
        "entidad": entidad, "absorbido": absorbido["nombre"], "sobreviviente": sobreviviente["nombre"],
        "lineas_movidas": movidas, "tipo_final": tipo_final, "neto_total": despues,
    }


def unir(usuario: dict, entidad: str, absorbido_id: int, sobreviviente_id: int,
         confirmar_tipo_distinto: bool = False) -> dict:
    """Une `absorbido` dentro de `sobreviviente` en una sola transaccion (todo o nada)."""
    with _conexion_escritura() as conn:  # commit al salir bien, rollback si algo falla
        resultado = _unir_en(conn, usuario, entidad, absorbido_id, sobreviviente_id, confirmar_tipo_distinto)
    st.cache_data.clear()  # las demas pantallas tienen que ver los datos nuevos ya
    return resultado


def nombre_base(nombre: str) -> str:
    """'Yuhmak (Automoviles)' -> 'yuhmak': nombre normalizado sin el parentesis del final."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", normalizar_nombre(nombre)).strip()


def grupos_por_nombre_base(filas: list[dict]) -> list[dict]:
    """Grupos de nombres que son variantes con parentesis de uno que se llama igual que la base
    ('Yuhmak' + 'Yuhmak (Automoviles)' + ...). Solo hay grupo si existe el nombre base sin
    parentesis: es el que sobrevive. Sin eso no se sugiere nada. Devuelve
    [{'base': fila, 'variantes': [fila, ...]}] ordenado por nombre."""
    por_base: dict[str, list[dict]] = {}
    for f in filas:
        por_base.setdefault(nombre_base(f["nombre"]), []).append(f)
    grupos = []
    for base, miembros in por_base.items():
        cabeza = [f for f in miembros if normalizar_nombre(f["nombre"]) == base]
        variantes = [f for f in miembros if normalizar_nombre(f["nombre"]) != base]
        if len(cabeza) == 1 and variantes:
            grupos.append({"base": cabeza[0], "variantes": sorted(variantes, key=lambda f: f["nombre"].lower())})
    return sorted(grupos, key=lambda g: g["base"]["nombre"].lower())


def unir_grupo(usuario: dict, entidad: str, sobreviviente_id: int, absorbidos_ids: list[int],
               confirmar_tipo_distinto: bool = False) -> dict:
    """Une varios nombres en el sobreviviente en UNA sola transaccion: si uno falla no se une ninguno."""
    if entidad not in ENTIDADES:
        raise ErrorFusion("Entidad desconocida.")
    if not absorbidos_ids or len(set(absorbidos_ids)) != len(absorbidos_ids):
        raise ErrorFusion("Elegí al menos un nombre para unir, sin repetidos.")
    tabla = ENTIDADES[entidad][0]
    with _conexion_escritura() as conn:
        filas = conn.execute(
            f"SELECT id, nombre FROM {tabla} WHERE id = ANY(%s)", ([sobreviviente_id, *absorbidos_ids],)
        ).fetchall()
        nombres = {f["id"]: f["nombre"] for f in filas}
        if len(nombres) != len(absorbidos_ids) + 1:
            raise ErrorFusion("Uno de los nombres ya no existe (¿ya se unió?). Recargá la pantalla.")
        base = normalizar_nombre(nombres[sobreviviente_id])
        if any(nombre_base(nombres[i]) != base for i in absorbidos_ids):
            raise ErrorFusion("Los nombres no pertenecen al mismo grupo.")
        resultados = [
            _unir_en(conn, usuario, entidad, i, sobreviviente_id, confirmar_tipo_distinto)
            for i in sorted(absorbidos_ids)
        ]
    st.cache_data.clear()
    return {
        "entidad": entidad, "sobreviviente": nombres[sobreviviente_id],
        "absorbidos": [r["absorbido"] for r in resultados],
        "lineas_movidas": sum(r["lineas_movidas"] for r in resultados),
        "tipo_final": resultados[-1]["tipo_final"], "neto_total": resultados[-1]["neto_total"],
    }


def descartar_sugerencia(usuario: dict, sugerencia_id: int) -> None:
    """'No es el mismo': la sugerencia pasa a descartada."""
    with _conexion_escritura() as conn:
        _exigir_admin(conn, usuario)
        cur = conn.execute(
            "UPDATE sugerencia_fusion SET estado = 'descartada' WHERE id = %s AND estado = 'abierta'",
            (sugerencia_id,),
        )
        if cur.rowcount == 0:
            raise ErrorFusion("Esa sugerencia ya no está abierta. Recargá la pantalla.")
    st.cache_data.clear()
