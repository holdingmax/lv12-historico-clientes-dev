"""Verificaciones de consistencia entre pantallas.

Corre contra la base de testing en modo SOLO LECTURA (necesita DATABASE_URL en .env):
    python -m unittest discover -s tests -t .
Las pruebas de matriz/formato no usan la base.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import consultas  # noqa: E402
from src.formato import normalizar_nombre, numero_ar  # noqa: E402
from src.matriz import armar_matriz, marcar_cambios  # noqa: E402

D = Decimal


class MatrizSinBase(unittest.TestCase):
    def test_se_perdio_y_nuevo(self):
        meses = [1, 2, 3, 4]
        # Estuvo en enero y febrero, cayo a cero en marzo.
        self.assertEqual(marcar_cambios({1: D(10), 2: D(10)}, meses), {3: "perdido"})
        # Aparece recien en marzo.
        self.assertEqual(marcar_cambios({3: D(5), 4: D(5)}, meses), {3: "nuevo"})
        # Vuelve despues de una pausa: marzo no es "nuevo" (ya tuvo neto en el anio),
        # pero se pierde de nuevo en abril.
        self.assertEqual(marcar_cambios({1: D(10), 3: D(7)}, meses), {2: "perdido", 4: "perdido"})
        # El primer mes nunca se marca.
        self.assertEqual(marcar_cambios({1: D(10)}, [1]), {})

    def test_orden_y_totales(self):
        filas = [
            {"cliente_id": 1, "nombre": "Ana", "tipo": "privado", "mes": 1, "neto": D(10)},
            {"cliente_id": 2, "nombre": "Beto", "tipo": "privado", "mes": 1, "neto": D(30)},
            {"cliente_id": 2, "nombre": "Beto", "tipo": "privado", "mes": 2, "neto": D(5)},
        ]
        m = armar_matriz(filas, [1, 2])
        self.assertEqual([c["nombre"] for c in m["clientes"]], ["Beto", "Ana"])
        self.assertEqual(m["totales_mes"], {1: D(40), 2: D(5)})
        self.assertEqual(m["total"], D(45))

    def test_formato(self):
        self.assertEqual(numero_ar(D("1234567.8")), "1.234.567,80")
        self.assertEqual(normalizar_nombre("  Ofertas   Libertad  Tucumán "), "ofertas libertad tucuman")


class ConsistenciaConLaBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.carga = consultas.ultima_carga()
        if cls.carga is None:
            raise unittest.SkipTest("No hay ninguna carga en la base.")
        cls.lote = cls.carga["id"]
        cls.tipos = [t["codigo"] for t in consultas.tipos_de_venta()]
        cls.anios = consultas.anios_con_datos(cls.lote)

    def total_tablero(self, anio, emisora_id, tipos):
        filas = consultas.neto_por_mes_y_tipo(self.lote, anio, emisora_id)
        return sum((f["neto"] for f in filas if f["tipo_venta"] in tipos), D(0))

    def total_matriz(self, anio, emisora_id, tipos, tipo_cliente=None):
        meses = consultas.meses_con_datos(self.lote, anio)
        filas = consultas.neto_por_cliente_y_mes(self.lote, anio, emisora_id, tipos, tipo_cliente, "")
        return armar_matriz(filas, meses)["total"]

    def test_tablero_igual_a_conciliacion(self):
        """El total del anio en el Tablero es la suma de los netos de la Conciliacion mes a mes."""
        for anio in self.anios:
            en_tablero = self.total_tablero(anio, None, self.tipos)
            en_conciliacion = D(0)
            for mes in consultas.meses_con_datos(self.lote, anio):
                filas = consultas.conciliacion_del_mes(self.lote, anio, mes)
                en_conciliacion += sum((f["neto_base"] for f in filas), D(0))
            self.assertEqual(en_tablero, en_conciliacion, f"anio {anio}")

    def test_matriz_igual_a_tablero(self):
        """Para los mismos filtros (anio, emisora, tipos de venta) los totales coinciden."""
        combinaciones_tipos = [self.tipos, self.tipos[:1], self.tipos[1:3], self.tipos[-2:]]
        for anio in self.anios:
            emisoras = [None] + [e["id"] for e in consultas.emisoras_con_datos(self.lote, anio)]
            for emisora_id in emisoras:
                for tipos in combinaciones_tipos:
                    self.assertEqual(
                        self.total_matriz(anio, emisora_id, tipos),
                        self.total_tablero(anio, emisora_id, tipos),
                        f"anio {anio}, emisora {emisora_id}, tipos {tipos}",
                    )

    def test_privado_mas_publica_igual_a_todos(self):
        for anio in self.anios:
            todos = self.total_matriz(anio, None, self.tipos)
            partes = sum(
                (self.total_matriz(anio, None, self.tipos, t) for t in ("privado", "publica")), D(0)
            )
            self.assertEqual(todos, partes)

    def test_busqueda_con_comodines_no_rompe(self):
        # Los % y _ del usuario se escapan: no deben devolver todo el listado.
        meses = consultas.meses_con_datos(self.lote, self.anios[0])
        todos = consultas.neto_por_cliente_y_mes(self.lote, self.anios[0], None, self.tipos, None, "")
        con_comodin = consultas.neto_por_cliente_y_mes(self.lote, self.anios[0], None, self.tipos, None, "%")
        self.assertTrue(meses)
        self.assertGreater(len(todos), 0)
        self.assertEqual(len(con_comodin), 0)


if __name__ == "__main__":
    unittest.main()
