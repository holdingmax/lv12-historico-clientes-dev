#!/usr/bin/env python
"""Importa el Resumen de Publicidades (.xls) a la base PostgreSQL del proyecto.

Uso: python scripts/import_resumen.py ruta/al/archivo.xls
Requiere DATABASE_URL en el entorno (ver .env.example) y las migraciones aplicadas.

Todo el archivo se carga en una sola transaccion: si algo falla, no queda nada a medias.
Si el archivo (por hash) ya fue importado, avisa y no cambia nada.
"""
import argparse
import difflib
import hashlib
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
import xlrd
from dotenv import load_dotenv

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Titulo del bloque (columna A, normalizado) -> tipo_venta. TELAM no tiene tipo definido.
BLOQUES = {
    "agencias": "AGENCIA",
    "local facturado": "LOCAL_FACTURADO",
    "local sin facturar": "LOCAL_SIN_FACTURAR",
    "coproducciones": "COPRODUCCION",
    "canjes facturados": "CANJE_FACTURADO",
    "canjes sin facturar": "CANJE_SIN_FACTURAR",
    "telam facturado-canje": None,
}
TIPOS_CON_OP = {"AGENCIA", "CANJE_FACTURADO"}  # en los demas la columna D es Vendedor

COL_A, COL_CLIENTE, COL_PERIODO, COL_D, COL_EMISORA, COL_NETO, COL_TOTAL = range(7)
ENCABEZADO_ESPERADO = {
    COL_CLIENTE: "cliente", COL_PERIODO: "periodo", COL_EMISORA: "emisora", COL_NETO: "neto",
}
UMBRAL_SIMILITUD = 0.9
CODIGO_OP = re.compile(r"\d+\s*[/\-]\s*\d+|\d{4,}")


class ErrorArchivo(Exception):
    """El archivo no tiene la estructura esperada."""


# ---------------------------------------------------------------- utilidades de texto

def norm(s: str) -> str:
    """Minusculas, sin tildes, espacios simples."""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower()).strip()


def clave_emisora(s: str) -> str:
    """Mayusculas/minusculas, espacios sobrantes y espacios alrededor de '/'."""
    return re.sub(r"\s*/\s*", "/", re.sub(r"\s+", " ", s.lower()).strip())


def num_a_texto(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(v)


def txt(sh, r: int, c: int) -> str:
    """Contenido de la celda como texto; los numeros enteros sin el '.0'."""
    if c >= sh.ncols:
        return ""
    t = sh.cell_type(r, c)
    if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    v = sh.cell_value(r, c)
    return num_a_texto(v) if t == xlrd.XL_CELL_NUMBER else str(v)


def neto_de(sh, r: int, c: int):
    if c < sh.ncols and sh.cell_type(r, c) == xlrd.XL_CELL_NUMBER:
        return round(sh.cell_value(r, c), 2)
    return None


# ---------------------------------------------------------------- lectura del Excel

def validar_fila1(sh, mes: str, anio: int) -> None:
    m = re.search(r"Mes:\s*(\S+)\s+A\S?o:\s*(\d{4})", txt(sh, 0, 1))
    if not m:
        raise ErrorArchivo(f"{sh.name}: la fila 1 no dice 'Mes: X  Año: AAAA'.")
    if norm(m.group(1)) != norm(mes) or int(m.group(2)) != anio:
        raise ErrorArchivo(
            f"{sh.name}: la fila 1 dice mes={m.group(1)} año={m.group(2)}, "
            f"no coincide con el nombre de la hoja."
        )


def leer_bloques(sh) -> list[dict]:
    inicios = [r for r in range(sh.nrows) if norm(txt(sh, r, COL_CLIENTE)) == "cliente"]
    bloques = []
    for i, r0 in enumerate(inicios):
        limite = inicios[i + 1] if i + 1 < len(inicios) else sh.nrows
        titulo = txt(sh, r0, COL_A).strip()
        clave = norm(titulo)
        if clave not in BLOQUES:
            raise ErrorArchivo(f"{sh.name} fila {r0 + 1}: bloque desconocido '{titulo}'.")
        for c, esperado in ENCABEZADO_ESPERADO.items():
            if norm(txt(sh, r0, c)) != esperado:
                raise ErrorArchivo(
                    f"{sh.name} fila {r0 + 1}: se esperaba '{esperado}' en la columna {c + 1}."
                )
        col_factura = next(
            (c for c in range(sh.ncols) if norm(txt(sh, r0, c)).startswith("factura")), None
        )
        filas, totales = [], None
        for r in range(r0 + 1, limite):
            if any(txt(sh, r, c).strip().lower() == "totales" for c in range(sh.ncols)):
                totales = neto_de(sh, r, COL_NETO)
                break
            if all(txt(sh, r, c).strip() == "" for c in range(sh.ncols)):
                continue
            filas.append(r)
        bloques.append({
            "titulo": titulo, "tipo": BLOQUES[clave], "filas": filas,
            "totales": totales, "col_factura": col_factura,
        })
    return bloques


def leer_hojas(wb) -> list[dict]:
    """Hojas mensuales con datos. Las vacias (sin filas y con Totales en 0) se ignoran."""
    hojas = []
    for sh in wb.sheets():
        m = re.fullmatch(r"(\w+) (\d{4})", sh.name.strip())
        if not m or m.group(1) not in MESES:
            continue
        mes, anio = MESES.index(m.group(1)) + 1, int(m.group(2))
        validar_fila1(sh, m.group(1), anio)
        bloques = leer_bloques(sh)
        if not any(b["filas"] or b["totales"] for b in bloques):
            continue
        hojas.append({"sh": sh, "anio": anio, "mes": mes, "bloques": bloques})
    return hojas


# ---------------------------------------------------------------- resolucion de nombres

class Entidades:
    """Clientes o agencias: busca por alias normalizado, crea los nuevos y detecta parecidos."""

    def __init__(self, cur, entidad: str):
        self.cur, self.entidad = cur, entidad
        cur.execute(f"SELECT alias_normalizado, {entidad}_id FROM {entidad}_alias")
        self.alias = dict(cur.fetchall())
        cur.execute(f"SELECT id, nombre FROM {entidad}")
        self.nombres = dict(cur.fetchall())
        self.creados = 0
        self.sugerencias = []  # (nombre_nuevo, nombre_parecido, similitud)
        self.sugerencias_omitidas = 0

    def _existe(self, id_: int) -> bool:
        self.cur.execute(f"SELECT 1 FROM {self.entidad} WHERE id = %s", (id_,))
        return self.cur.fetchone() is not None

    def resolver(self, crudo: str, lote_id: int) -> int:
        nombre = crudo.strip()
        clave = norm(nombre)
        if clave in self.alias:
            return self.alias[clave]

        parecidos: dict[int, float] = {}
        for otra, id_ in self.alias.items():
            sm = difflib.SequenceMatcher(None, clave, otra)
            if sm.real_quick_ratio() < UMBRAL_SIMILITUD or sm.quick_ratio() < UMBRAL_SIMILITUD:
                continue
            s = sm.ratio()
            if s >= UMBRAL_SIMILITUD and s > parecidos.get(id_, 0):
                parecidos[id_] = s

        self.cur.execute(
            f"INSERT INTO {self.entidad} (nombre) VALUES (%s) "
            f"ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING id",
            (nombre,),
        )
        nuevo = self.cur.fetchone()[0]
        self.cur.execute(
            f"INSERT INTO {self.entidad}_alias (alias_normalizado, {self.entidad}_id) "
            f"VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (clave, nuevo),
        )
        self.alias[clave] = nuevo
        self.nombres[nuevo] = nombre
        self.creados += 1

        for parecido, s in sorted(parecidos.items(), key=lambda x: -x[1]):
            # Antes de insertar la sugerencia, ambos ids tienen que existir en su tabla.
            if parecido == nuevo or not (self._existe(nuevo) and self._existe(parecido)):
                self.sugerencias_omitidas += 1
                continue
            self.cur.execute(
                "INSERT INTO sugerencia_fusion (lote_id, entidad, nombre_id, parecido_id, similitud) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (lote_id, self.entidad, nuevo, parecido, round(s, 3)),
            )
            self.sugerencias.append((nombre, self.nombres[parecido], round(s, 3)))
        return nuevo


class Emisoras:
    """Emisoras tal como se vieron por primera vez; la clave ignora mayusculas y espacios."""

    def __init__(self, cur):
        self.cur = cur
        cur.execute("SELECT id, nombre FROM emisora")
        self.por_clave = {clave_emisora(n): i for i, n in cur.fetchall()}
        self.creadas = []

    def resolver(self, crudo: str):
        nombre = crudo.strip()
        if not nombre:
            return None
        clave = clave_emisora(nombre)
        if clave not in self.por_clave:
            self.cur.execute(
                "INSERT INTO emisora (nombre) VALUES (%s) RETURNING id", (nombre,)
            )
            self.por_clave[clave] = self.cur.fetchone()[0]
            self.creadas.append(nombre)
        return self.por_clave[clave]


# ---------------------------------------------------------------- importacion

def importar(ruta: Path, url: str) -> int:
    contenido = ruta.read_bytes()
    hash_archivo = hashlib.sha256(contenido).hexdigest()
    wb = xlrd.open_workbook(file_contents=contenido)
    hojas = leer_hojas(wb)  # valida la estructura antes de escribir nada
    if not hojas:
        raise ErrorArchivo("No se encontraron hojas mensuales con datos.")

    lineas, rechazadas, controles, codigos_op = [], [], [], []
    with psycopg.connect(url) as conn:  # una transaccion: commit al final o rollback si falla
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, fecha FROM lote_importacion WHERE hash_archivo = %s", (hash_archivo,)
            )
            previo = cur.fetchone()
            if previo:
                print(f"Archivo ya importado (lote {previo[0]}, {previo[1]:%Y-%m-%d %H:%M}). "
                      f"No se cambió nada.")
                return 0

            cur.execute(
                "INSERT INTO lote_importacion (archivo, hash_archivo) VALUES (%s, %s) RETURNING id",
                (ruta.name, hash_archivo),
            )
            lote_id = cur.fetchone()[0]
            clientes = Entidades(cur, "cliente")
            agencias = Entidades(cur, "agencia")
            emisoras = Emisoras(cur)

            for hoja in hojas:
                sh, anio, mes = hoja["sh"], hoja["anio"], hoja["mes"]
                for b in hoja["bloques"]:
                    tipo = b["tipo"]
                    if tipo and b["totales"] is not None:
                        controles.append((lote_id, anio, mes, tipo, b["totales"]))
                    agencia_actual = None  # el nombre puede venir solo en la primera fila del grupo
                    for r in b["filas"]:
                        fila = r + 1
                        contenido_fila = " | ".join(txt(sh, r, c) for c in range(sh.ncols))
                        if tipo is None:
                            rechazadas.append((sh.name, fila, f"bloque '{b['titulo']}' sin tipo de venta", contenido_fila))
                            continue
                        if tipo == "COPRODUCCION":  # el cliente viene en la columna A
                            cliente_crudo = txt(sh, r, COL_A)
                        else:
                            cliente_crudo = txt(sh, r, COL_CLIENTE)
                        neto = neto_de(sh, r, COL_NETO)
                        if not cliente_crudo.strip():
                            rechazadas.append((sh.name, fila, "sin cliente", contenido_fila))
                            continue
                        if neto is None:
                            rechazadas.append((sh.name, fila, "sin neto", contenido_fila))
                            continue

                        agencia_id = None
                        if tipo == "AGENCIA":
                            nombre_ag = txt(sh, r, COL_A).strip()
                            if nombre_ag:
                                agencia_actual = nombre_ag
                            if agencia_actual is None:
                                rechazadas.append((sh.name, fila, "sin agencia", contenido_fila))
                                continue
                            agencia_id = agencias.resolver(agencia_actual, lote_id)

                        cliente_id = clientes.resolver(cliente_crudo, lote_id)
                        valor_d = txt(sh, r, COL_D).strip() or None
                        op = valor_d if tipo in TIPOS_CON_OP else None
                        vendedor = None if tipo in TIPOS_CON_OP else valor_d
                        if vendedor and CODIGO_OP.fullmatch(vendedor):
                            codigos_op.append((sh.name, fila, tipo, cliente_crudo.strip(), vendedor))
                        factura = None
                        if b["col_factura"] is not None:
                            factura = txt(sh, r, b["col_factura"]).strip() or None
                        total = neto_de(sh, r, COL_TOTAL)
                        periodo = txt(sh, r, COL_PERIODO)
                        lineas.append((
                            lote_id, sh.name, fila, anio, mes, periodo if periodo.strip() else None,
                            tipo, cliente_id, agencia_id, emisoras.resolver(txt(sh, r, COL_EMISORA)),
                            op, vendedor, factura, neto, total,
                        ))

            cur.executemany(
                "INSERT INTO orden_linea (lote_id, hoja, fila_origen, anio, mes, periodo_texto, "
                "tipo_venta, cliente_id, agencia_id, emisora_id, op, vendedor, factura_nro, "
                "neto, total_con_iva) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                lineas,
            )
            cur.executemany(
                "INSERT INTO fila_rechazada (lote_id, hoja, fila, motivo, contenido) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(lote_id, *x) for x in rechazadas],
            )
            cur.executemany(
                "INSERT INTO control_total_excel (lote_id, anio, mes, tipo_venta, neto) "
                "VALUES (%s, %s, %s, %s, %s)",
                controles,
            )
            cur.execute(
                "UPDATE lote_importacion SET filas_ok = %s, filas_rechazadas = %s WHERE id = %s",
                (len(lineas), len(rechazadas), lote_id),
            )

            cur.execute(
                "SELECT mes, tipo_venta, count(*), sum(neto) FROM orden_linea "
                "WHERE lote_id = %s GROUP BY 1, 2", (lote_id,),
            )
            en_base = {(m, t): (n, s) for m, t, n, s in cur.fetchall()}
            cur.execute(
                "SELECT mes, tipo_venta, neto FROM control_total_excel WHERE lote_id = %s",
                (lote_id,),
            )
            en_excel = {(m, t): s for m, t, s in cur.fetchall()}
            cur.execute("SELECT codigo, nombre FROM tipo_venta ORDER BY orden")
            tipos = cur.fetchall()

    imprimir_resumen(
        ruta, lote_id, tipos, en_base, en_excel, rechazadas, clientes, agencias,
        emisoras, codigos_op, len(lineas),
    )
    return 0


# ---------------------------------------------------------------- resumen en pantalla

def fmt(x) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_resumen(ruta, lote_id, tipos, en_base, en_excel, rechazadas, clientes, agencias,
                     emisoras, codigos_op, total_lineas):
    print(f"\n=== Importación terminada: {ruta.name} (lote {lote_id}) ===")
    print(f"Filas cargadas: {total_lineas} | rechazadas: {len(rechazadas)}")
    print(f"Creados: {clientes.creados} clientes, {agencias.creados} agencias, "
          f"{len(emisoras.creadas)} emisoras")

    meses = sorted({m for m, _ in en_base} | {m for m, _ in en_excel})
    print("\n--- Líneas por mes y tipo ---")
    print(f"{'Mes':<11}" + "".join(f"{n[:16]:>18}" for _, n in tipos) + f"{'Total':>8}")
    for m in meses:
        cant = [en_base.get((m, c), (0, 0))[0] for c, _ in tipos]
        print(f"{MESES[m - 1]:<11}" + "".join(f"{n:>18}" for n in cant) + f"{sum(cant):>8}")

    print("\n--- Filas rechazadas ---")
    if not rechazadas:
        print("Ninguna.")
    for motivo, n in Counter(x[2] for x in rechazadas).items():
        print(f"{n} filas: {motivo}")
    for hoja, fila, motivo, cont in rechazadas[:50]:
        print(f"  {hoja} fila {fila}: {motivo} -> {cont}")

    print("\n--- Sugerencias de fusión (similitud >= 0,9; no afectan las líneas) ---")
    hay = False
    for ent in (clientes, agencias):
        for nuevo, parecido, s in ent.sugerencias:
            hay = True
            print(f"  [{ent.entidad}] '{nuevo}' ~ '{parecido}' ({s})")
        if ent.sugerencias_omitidas:
            print(f"  ({ent.sugerencias_omitidas} sugerencias de {ent.entidad} omitidas: id inexistente)")
    if not hay:
        print("Ninguna.")

    print("\n--- Vendedores con código de OP (consultar a Maxi) ---")
    if not codigos_op:
        print("Ninguno.")
    for hoja, fila, tipo, cliente, codigo in codigos_op:
        print(f"  {hoja} fila {fila} [{tipo}] {cliente}: {codigo}")

    print("\n--- Control: neto en la base vs. Totales del Excel ---")
    print(f"{'Mes':<11}{'Tipo':<22}{'Base':>18}{'Excel':>18}{'Diferencia':>16}")
    tot_b = tot_e = 0
    for m in meses:
        for codigo, nombre in tipos:
            if (m, codigo) not in en_base and (m, codigo) not in en_excel:
                continue
            b = en_base.get((m, codigo), (0, 0))[1]
            e = en_excel.get((m, codigo))
            tot_b += b
            tot_e += e or 0
            dif = None if e is None else b - e
            marca = "" if dif == 0 else "  <-- DIFERENCIA" if dif is not None else "  <-- sin total en Excel"
            print(f"{MESES[m - 1]:<11}{nombre:<22}{fmt(b):>18}{fmt(e) if e is not None else '-':>18}"
                  f"{fmt(dif) if dif is not None else '-':>16}{marca}")
    print(f"{'TOTAL':<33}{fmt(tot_b):>18}{fmt(tot_e):>18}{fmt(tot_b - tot_e):>16}")


# ---------------------------------------------------------------- main

def enmascarar(msg: str, url: str) -> str:
    """Tapa cualquier parte de la URL de la base en un mensaje de error."""
    partes = {url}
    try:
        d = psycopg.conninfo.conninfo_to_dict(url)
        partes |= {str(v) for v in d.values() if v}
    except Exception:
        pass
    for p in sorted(partes, key=len, reverse=True):
        msg = msg.replace(p, "***")
    return msg


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Importa el Resumen de Publicidades (.xls).")
    parser.add_argument("archivo", type=Path, help="ruta al .xls")
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Falta DATABASE_URL. Copia .env.example a .env y completa la URL.")
    if not args.archivo.is_file():
        sys.exit(f"No existe el archivo: {args.archivo}")
    try:
        sys.exit(importar(args.archivo, url))
    except ErrorArchivo as e:
        sys.exit(f"Archivo inválido, no se cargó nada: {e}")
    except Exception as e:
        sys.exit(f"Falló la importación, no se cargó nada: {type(e).__name__}: "
                 f"{enmascarar(str(e), url)}")


if __name__ == "__main__":
    main()
