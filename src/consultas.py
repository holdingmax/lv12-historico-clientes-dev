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


# ---------------------------------------------------------------- tablero y clientes por mes
# Filtro de emisora: None = todas. El mismo valor se pasa dos veces (IS NULL / igualdad).
FILTRO_EMISORA = "(%s::int IS NULL OR l.emisora_id = %s)"


def tipos_de_venta() -> list[dict]:
    return _consultar("SELECT codigo, nombre, orden FROM tipo_venta ORDER BY orden")


def anios_con_datos(lote: int) -> list[int]:
    filas = _consultar(
        "SELECT DISTINCT anio FROM orden_linea WHERE lote_id = %s ORDER BY anio DESC", (lote,)
    )
    return [f["anio"] for f in filas]


def emisoras_con_datos(lote: int, anio: int) -> list[dict]:
    return _consultar(
        """
        SELECT DISTINCT e.id, e.nombre
        FROM orden_linea l JOIN emisora e ON e.id = l.emisora_id
        WHERE l.lote_id = %s AND l.anio = %s
        ORDER BY e.nombre
        """,
        (lote, anio),
    )


def meses_con_datos(lote: int, anio: int) -> list[int]:
    filas = _consultar(
        "SELECT DISTINCT mes FROM orden_linea WHERE lote_id = %s AND anio = %s ORDER BY mes",
        (lote, anio),
    )
    return [f["mes"] for f in filas]


def neto_por_mes_y_tipo(lote: int, anio: int, emisora_id: int | None) -> list[dict]:
    """Neto (y total con IVA) por mes y tipo de venta. Solo aparecen los meses con lineas."""
    return _consultar(
        f"""
        SELECT l.mes, l.tipo_venta, sum(l.neto) AS neto, sum(l.total_con_iva) AS total_con_iva
        FROM orden_linea l
        WHERE l.lote_id = %s AND l.anio = %s AND {FILTRO_EMISORA}
        GROUP BY l.mes, l.tipo_venta
        ORDER BY l.mes, l.tipo_venta
        """,
        (lote, anio, emisora_id, emisora_id),
    )


def neto_por_mes_y_clase(lote: int, anio: int, emisora_id: int | None) -> list[dict]:
    """Neto (y total con IVA) por mes y tipo de cliente ('publica' / 'privado')."""
    return _consultar(
        f"""
        SELECT l.mes, cl.tipo, sum(l.neto) AS neto, sum(l.total_con_iva) AS total_con_iva
        FROM orden_linea l
        JOIN cliente cl ON cl.id = l.cliente_id
        WHERE l.lote_id = %s AND l.anio = %s AND {FILTRO_EMISORA}
        GROUP BY l.mes, cl.tipo
        ORDER BY l.mes, cl.tipo
        """,
        (lote, anio, emisora_id, emisora_id),
    )


def clientes_activos_por_mes(lote: int, anio: int, emisora_id: int | None) -> dict[int, int]:
    """Clientes con neto mayor a cero en el mes (mismo criterio que la matriz de clientes)."""
    filas = _consultar(
        f"""
        SELECT mes, count(*) AS clientes FROM (
            SELECT l.mes, l.cliente_id
            FROM orden_linea l
            WHERE l.lote_id = %s AND l.anio = %s AND {FILTRO_EMISORA}
            GROUP BY l.mes, l.cliente_id
            HAVING sum(l.neto) > 0
        ) t
        GROUP BY mes
        """,
        (lote, anio, emisora_id, emisora_id),
    )
    return {f["mes"]: f["clientes"] for f in filas}


def _patron_busqueda(texto_normalizado: str) -> str | None:
    """Patron LIKE 'contiene' con los comodines del usuario escapados."""
    if not texto_normalizado:
        return None
    escapado = (
        texto_normalizado.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escapado}%"


def neto_por_cliente_y_mes(
    lote: int, anio: int, emisora_id: int | None, tipos: list[str],
    tipo_cliente: str | None, busqueda_normalizada: str,
) -> list[dict]:
    """Una fila por cliente y mes con el neto, ya sumado en la base."""
    patron = _patron_busqueda(busqueda_normalizada)
    return _consultar(
        rf"""
        SELECT cl.id AS cliente_id, cl.nombre, cl.tipo, l.mes, sum(l.neto) AS neto
        FROM orden_linea l
        JOIN cliente cl ON cl.id = l.cliente_id
        WHERE l.lote_id = %s AND l.anio = %s AND {FILTRO_EMISORA}
          AND l.tipo_venta = ANY(%s)
          AND (%s::text IS NULL OR cl.tipo = %s)
          AND (%s::text IS NULL OR EXISTS (
                SELECT 1 FROM cliente_alias a
                WHERE a.cliente_id = cl.id AND a.alias_normalizado LIKE %s ESCAPE '\'))
        GROUP BY cl.id, cl.nombre, cl.tipo, l.mes
        ORDER BY cl.id, l.mes
        """,
        (lote, anio, emisora_id, emisora_id, tipos, tipo_cliente, tipo_cliente, patron, patron),
    )


def lineas_de_cliente(
    lote: int, cliente_id: int, anio: int, emisora_id: int | None, tipos: list[str]
) -> list[dict]:
    return _consultar(
        f"""
        SELECT l.mes, t.nombre AS tipo, ag.nombre AS agencia, e.nombre AS emisora,
               l.op, l.neto
        FROM orden_linea l
        JOIN tipo_venta t ON t.codigo = l.tipo_venta
        LEFT JOIN agencia ag ON ag.id = l.agencia_id
        LEFT JOIN emisora e ON e.id = l.emisora_id
        WHERE l.lote_id = %s AND l.cliente_id = %s AND l.anio = %s AND {FILTRO_EMISORA}
          AND l.tipo_venta = ANY(%s)
        ORDER BY l.mes, t.orden, l.fila_origen
        """,
        (lote, cliente_id, anio, emisora_id, emisora_id, tipos),
    )


def clientes_con_sugerencia_abierta() -> set[int]:
    filas = _consultar(
        """
        SELECT nombre_id AS id FROM sugerencia_fusion WHERE entidad = 'cliente' AND estado = 'abierta'
        UNION
        SELECT parecido_id FROM sugerencia_fusion WHERE entidad = 'cliente' AND estado = 'abierta'
        """
    )
    return {f["id"] for f in filas}


def cantidad_de_duplicados_posibles() -> int:
    filas = _consultar(
        "SELECT count(*) AS n FROM sugerencia_fusion WHERE entidad = 'cliente' AND estado = 'abierta'"
    )
    return filas[0]["n"]


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
