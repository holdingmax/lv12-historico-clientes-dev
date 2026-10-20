"""Consultas de solo lectura para las pantallas. Ninguna escribe en la base."""
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from src.db import get_connection_lectura

# Vendedor que en realidad parece un codigo de OP (ej. 772813/1)
CODIGO_OP_SQL = r"^\d+\s*[/-]\s*\d+$|^\d{4,}$"


@st.cache_data(ttl=60, show_spinner=False)
def _consultar(sql: str, params: tuple = ()) -> list[dict]:
    for intento in (1, 2):
        try:
            with get_connection_lectura().cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except psycopg.OperationalError:
            # La conexion guardada puede haberse cortado (Render cierra las inactivas).
            get_connection_lectura.clear()
            if intento == 2:
                raise


def ultima_carga() -> dict | None:
    filas = _consultar(
        "SELECT id, archivo, fecha, filas_ok, filas_rechazadas FROM lote_importacion "
        "ORDER BY fecha DESC, id DESC LIMIT 1"
    )
    return filas[0] if filas else None


def conciliacion_del_mes(lote: int, anio: int, mes: int) -> list[dict]:
    """Por tipo de venta: neto en la base y neto del Excel (None si el Excel no trae total)."""
    return _consultar(
        """
        SELECT t.codigo, t.nombre, COALESCE(b.neto, 0) AS neto_base, c.neto AS neto_excel
        FROM tipo_venta t
        LEFT JOIN (SELECT tipo_venta, sum(neto) AS neto FROM orden_linea
                   WHERE lote_id = %s AND anio = %s AND mes = %s GROUP BY 1) b
               ON b.tipo_venta = t.codigo
        LEFT JOIN control_total_excel c
               ON c.lote_id = %s AND c.anio = %s AND c.mes = %s AND c.tipo_venta = t.codigo
        ORDER BY t.orden
        """,
        (lote, anio, mes, lote, anio, mes),
    )


def diferencias_de_la_carga(lote: int) -> list[dict]:
    """Todos los meses y tipos donde la base no coincide con el total del Excel."""
    return _consultar(
        """
        SELECT c.anio, c.mes, t.codigo, t.nombre, COALESCE(b.neto, 0) AS neto_base,
               c.neto AS neto_excel
        FROM control_total_excel c
        JOIN tipo_venta t ON t.codigo = c.tipo_venta
        LEFT JOIN (SELECT anio, mes, tipo_venta, sum(neto) AS neto FROM orden_linea
                   WHERE lote_id = %s GROUP BY 1, 2, 3) b
               ON b.anio = c.anio AND b.mes = c.mes AND b.tipo_venta = c.tipo_venta
        WHERE c.lote_id = %s AND COALESCE(b.neto, 0) <> c.neto
        ORDER BY c.anio, c.mes, t.orden
        """,
        (lote, lote),
    )


def meses_de_la_carga(lote: int) -> list[tuple[int, int]]:
    filas = _consultar(
        "SELECT anio, mes FROM control_total_excel WHERE lote_id = %s "
        "UNION SELECT anio, mes FROM orden_linea WHERE lote_id = %s ORDER BY 1, 2",
        (lote, lote),
    )
    return [(f["anio"], f["mes"]) for f in filas]


def lineas_del_tipo(lote: int, anio: int, mes: int, tipo: str) -> list[dict]:
    return _consultar(
        """
        SELECT l.hoja, l.fila_origen AS fila, cl.nombre AS cliente, ag.nombre AS agencia,
               l.periodo_texto AS periodo, e.nombre AS emisora, l.neto
        FROM orden_linea l
        JOIN cliente cl ON cl.id = l.cliente_id
        LEFT JOIN agencia ag ON ag.id = l.agencia_id
        LEFT JOIN emisora e ON e.id = l.emisora_id
        WHERE l.lote_id = %s AND l.anio = %s AND l.mes = %s AND l.tipo_venta = %s
        ORDER BY l.fila_origen
        """,
        (lote, anio, mes, tipo),
    )


def lineas_con_codigo_de_op(lote: int) -> list[dict]:
    return _consultar(
        """
        SELECT l.anio, l.mes, l.hoja, l.fila_origen AS fila, cl.nombre AS cliente,
               l.periodo_texto AS periodo, e.nombre AS emisora, l.neto, l.vendedor
        FROM orden_linea l
        JOIN cliente cl ON cl.id = l.cliente_id
        LEFT JOIN emisora e ON e.id = l.emisora_id
        WHERE l.lote_id = %s AND l.vendedor ~ %s
        ORDER BY l.anio, l.mes, l.fila_origen
        """,
        (lote, CODIGO_OP_SQL),
    )


def sugerencias_abiertas() -> list[dict]:
    return _consultar(
        """
        SELECT s.entidad, n.nombre, p.nombre AS parecido, s.similitud
        FROM sugerencia_fusion s
        JOIN cliente n ON n.id = s.nombre_id
        JOIN cliente p ON p.id = s.parecido_id
        WHERE s.entidad = 'cliente' AND s.estado = 'abierta'
        UNION ALL
        SELECT s.entidad, n.nombre, p.nombre, s.similitud
        FROM sugerencia_fusion s
        JOIN agencia n ON n.id = s.nombre_id
        JOIN agencia p ON p.id = s.parecido_id
        WHERE s.entidad = 'agencia' AND s.estado = 'abierta'
        ORDER BY 1, 4 DESC, 2
        """
    )
