"""Matriz cliente x mes: armado y marcas de 'se perdio' / 'nuevo'. Sin Streamlit ni base."""
from decimal import Decimal

CERO = Decimal(0)


def armar_matriz(filas: list[dict], meses: list[int]) -> dict:
    """filas: una por cliente y mes (ya sumadas en la base). Ordena por total descendente."""
    clientes: dict[int, dict] = {}
    for f in filas:
        c = clientes.setdefault(
            f["cliente_id"],
            {"id": f["cliente_id"], "nombre": f["nombre"], "tipo": f["tipo"], "por_mes": {}},
        )
        c["por_mes"][f["mes"]] = c["por_mes"].get(f["mes"], CERO) + f["neto"]
    for c in clientes.values():
        c["total"] = sum(c["por_mes"].values(), CERO)
        c["marcas"] = marcar_cambios(c["por_mes"], meses)
    lista = sorted(clientes.values(), key=lambda c: (-c["total"], c["nombre"].lower()))
    totales_mes = {m: sum((c["por_mes"].get(m, CERO) for c in lista), CERO) for m in meses}
    return {
        "clientes": lista,
        "totales_mes": totales_mes,
        "total": sum(totales_mes.values(), CERO),
    }


def marcar_cambios(por_mes: dict[int, Decimal], meses: list[int]) -> dict[int, str]:
    """'perdido': tuvo neto el mes anterior y este mes quedo en cero.
    'nuevo': tiene neto este mes y no tuvo en ningun mes anterior del anio.
    El primer mes no se marca (no hay con que compararlo) y tampoco los meses que vienen
    despues de un salto en el calendario."""
    marcas: dict[int, str] = {}
    for i, m in enumerate(meses):
        if i == 0 or meses[i - 1] != m - 1:
            continue
        actual = por_mes.get(m, CERO)
        anterior = por_mes.get(m - 1, CERO)
        if anterior > 0 and actual <= 0:
            marcas[m] = "perdido"
        elif actual > 0 and not any(por_mes.get(x, CERO) > 0 for x in meses[:i]):
            marcas[m] = "nuevo"
    return marcas
