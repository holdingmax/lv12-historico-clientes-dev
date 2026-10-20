"""Pauta publica vs privada: marcas en la base, totales y pantallas.

Usa la base de testing en modo SOLO LECTURA (necesita DATABASE_URL en .env) y la migracion
005 aplicada. Las pantallas se prueban con el login simulado (no crean usuarios).
    python -m unittest discover -s tests -t .
"""
import io
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from openpyxl import load_workbook  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from src import consultas  # noqa: E402
from src.exportar import matriz_a_excel  # noqa: E402
from src.matriz import armar_matriz  # noqa: E402

D = Decimal
TOTAL_GENERAL_2026 = D("134946971.06")  # total del archivo cargado (coincide con Conciliacion)
PUBLICOS = {
    "CAJA POPULAR DE AHORRO", "Ente de Turismo", "MUNICIPALIDAD BRS", "MUNICIPALIDAD DE TRANCAS",
    "MUNICIPALIDAD FAMAILLA", "MUNICIPALIDAD LULES (Expo Lules)", "MUNICIPALIDAD TAFI DEL VALLE", "SAT",
}
USUARIO_SIMULADO = {"id": 0, "email": "prueba@example.invalid", "nombre": "Prueba",
                    "rol": "operador", "debe_cambiar_password": False}


class MarcasEnLaBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.carga = consultas.ultima_carga()
        if cls.carga is None:
            raise unittest.SkipTest("No hay ninguna carga en la base.")
        cls.lote = cls.carga["id"]
        cls.anios = consultas.anios_con_datos(cls.lote)
        cls.tipos = [t["codigo"] for t in consultas.tipos_de_venta()]

    def test_clientes_marcados_como_publica(self):
        filas = consultas._consultar("SELECT nombre, tipo FROM cliente")
        self.assertEqual({f["nombre"] for f in filas if f["tipo"] == "publica"}, PUBLICOS)
        tipos = {f["nombre"]: f["tipo"] for f in filas}
        self.assertEqual(tipos["Asispre"], "privado")  # pendiente de que el gerente confirme
        self.assertEqual(tipos["Agencia Cordoba Turismo"], "privado")  # agencia privada, no el Ente

    def test_publica_mas_privada_igual_al_total_en_todos_los_meses(self):
        for anio in self.anios:
            emisoras = [None] + [e["id"] for e in consultas.emisoras_con_datos(self.lote, anio)]
            for emisora_id in emisoras:
                por_clase, por_tipo = {}, {}
                for f in consultas.neto_por_mes_y_clase(self.lote, anio, emisora_id):
                    por_clase[f["mes"]] = por_clase.get(f["mes"], D(0)) + f["neto"]
                for f in consultas.neto_por_mes_y_tipo(self.lote, anio, emisora_id):
                    por_tipo[f["mes"]] = por_tipo.get(f["mes"], D(0)) + f["neto"]
                self.assertEqual(por_clase, por_tipo, f"anio {anio}, emisora {emisora_id}")

    def test_total_general_sigue_siendo_el_del_archivo(self):
        total = sum((f["neto"] for f in consultas.neto_por_mes_y_clase(self.lote, 2026, None)), D(0))
        self.assertEqual(total, TOTAL_GENERAL_2026)

    def test_hay_pauta_publica_en_cada_mes_con_datos(self):
        meses_con_publica = {f["mes"] for f in consultas.neto_por_mes_y_clase(self.lote, 2026, None) if f["tipo"] == "publica"}
        self.assertEqual(meses_con_publica, set(consultas.meses_con_datos(self.lote, 2026)))

    def test_filtro_tipo_de_cliente_de_clientes_por_mes_devuelve_datos(self):
        meses = consultas.meses_con_datos(self.lote, 2026)
        def matriz(tipo_cliente):
            filas = consultas.neto_por_cliente_y_mes(self.lote, 2026, None, self.tipos, tipo_cliente, "")
            return armar_matriz(filas, meses)
        publica, privada, todos = matriz("publica"), matriz("privado"), matriz(None)
        self.assertEqual({c["nombre"] for c in publica["clientes"]}, PUBLICOS)
        self.assertTrue(all(c["tipo"] == "publica" for c in publica["clientes"]))
        self.assertTrue(all(c["tipo"] == "privado" for c in privada["clientes"]))
        self.assertEqual(len(publica["clientes"]) + len(privada["clientes"]), len(todos["clientes"]))
        self.assertEqual(publica["total"] + privada["total"], todos["total"])
        self.assertEqual(todos["total"], TOTAL_GENERAL_2026)
        # La matriz de publicos coincide con lo que muestra el Tablero como publica.
        tablero = sum((f["neto"] for f in consultas.neto_por_mes_y_clase(self.lote, 2026, None) if f["tipo"] == "publica"), D(0))
        self.assertEqual(publica["total"], tablero)


class Excel(unittest.TestCase):
    def test_la_exportacion_incluye_el_tipo_y_los_totales(self):
        filas = [
            {"cliente_id": 1, "nombre": "SAT", "tipo": "publica", "mes": 1, "neto": D("100.50")},
            {"cliente_id": 2, "nombre": "Privado SA", "tipo": "privado", "mes": 1, "neto": D("300")},
            {"cliente_id": 2, "nombre": "Privado SA", "tipo": "privado", "mes": 2, "neto": D("50")},
        ]
        matriz = armar_matriz(filas, [1, 2])
        hoja = load_workbook(io.BytesIO(matriz_a_excel(matriz, [1, 2], {1}, 2026))).active
        self.assertEqual([c.value for c in hoja[1]],
                         ["Cliente", "Tipo", "Ene 2026", "Feb 2026", "Total", "Participación", "Posible duplicado"])
        self.assertEqual([c.value for c in hoja[2]][:5], ["Privado SA", "Privada", 300, 50, 350])
        self.assertEqual([c.value for c in hoja[3]][:5], ["SAT", "Pública", 100.5, None, 100.5])
        self.assertEqual(hoja["G3"].value, "Sí")  # SAT con sugerencia abierta
        self.assertEqual([c.value for c in hoja[4]][:5], ["Total", None, 400.5, 50, 450.5])  # celda vacia


class Pantallas(unittest.TestCase):
    """Con el login simulado: lo que se prueba es la pantalla, no el acceso."""

    def correr(self, archivo):
        with mock.patch("src.auth.require_login", return_value=USUARIO_SIMULADO):
            return AppTest.from_file(str(RAIZ / archivo), default_timeout=120).run()

    def test_tablero_por_tipo_de_venta_trae_el_indicador_de_pauta_publica(self):
        at = self.correr("pantallas/tablero.py")
        self.assertEqual(len(at.exception), 0)
        etiquetas = {m.label: m.value for m in at.metric}
        self.assertEqual(len(at.metric), 5)
        publica = next(v for k, v in etiquetas.items() if k.startswith("Pauta pública"))
        self.assertRegex(publica, r"^\d+,\d %$")  # ej. 12,3 %

    def test_tablero_modo_publica_vs_privada(self):
        with mock.patch("src.auth.require_login", return_value=USUARIO_SIMULADO):
            at = AppTest.from_file(str(RAIZ / "pantallas/tablero.py"), default_timeout=120).run()
            at.radio[0].set_value("Pública vs Privada").run()
        self.assertEqual(len(at.exception), 0)
        tabla = next(m.value for m in at.markdown if "<table" in m.value)
        for texto in (">Pública<", ">Privada<", ">Total<", ">% Pública<"):
            self.assertIn(texto, tabla)
        self.assertNotIn(">Agencias<", tabla)
        self.assertIn("Neto por mes: pública y privada", [s.value for s in at.subheader])

    def test_clientes_por_mes_muestra_la_columna_tipo_y_el_filtro_funciona(self):
        with mock.patch("src.auth.require_login", return_value=USUARIO_SIMULADO):
            at = AppTest.from_file(str(RAIZ / "pantallas/clientes_mes.py"), default_timeout=120).run()
            self.assertEqual(len(at.exception), 0)
            tabla = next(m.value for m in at.markdown if "<table" in m.value)
            self.assertIn(">Tipo<", tabla)
            self.assertIn(">Pública<", tabla)
            self.assertIn(">Privada<", tabla)
            at.selectbox[2].set_value("Pública").run()
            resumen = [m.value for m in at.markdown if "clientes**" in m.value]
            self.assertEqual(resumen, ["**8 clientes** · ordenados por total, de mayor a menor"])
            tabla = next(m.value for m in at.markdown if "<table" in m.value)
            self.assertNotIn(">Privada<", tabla)


if __name__ == "__main__":
    unittest.main()
