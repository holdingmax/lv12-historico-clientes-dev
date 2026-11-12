"""Union de nombres duplicados: transaccion, alias, sugerencias, roles, importador y pantalla.

Usa la base de testing (DATABASE_URL en .env). Todo lo que crea es descartable y no toca datos
reales: un lote propio con fecha vieja (nunca es "la ultima carga"), clientes y agencias
"Test Fusion ..." y usuarios test-auth-*@example.invalid. Se borra al terminar cada prueba.
    python -m unittest discover -s tests -t .
"""
import importlib.util
import itertools
import os
import secrets
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import psycopg
from psycopg.rows import dict_row

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import auth, consultas, fusion  # noqa: E402
from src.formato import normalizar_nombre  # noqa: E402
from src.matriz import armar_matriz  # noqa: E402
from src.navegacion import paginas_para  # noqa: E402
from tests.test_auth import email_de_prueba, limpiar as limpiar_usuarios, password_aleatoria  # noqa: E402

D = Decimal
_CONEXION = None


def consulta(sql, params=()):
    """Consulta de apoyo de los tests, con UNA conexion reutilizada (abrir una por consulta contra la
    base remota tardaba segundos). Autocommit: cada sentencia queda confirmada, como antes."""
    global _CONEXION
    if _CONEXION is None or _CONEXION.closed:
        _CONEXION = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    cur = _CONEXION.execute(sql, params or None)  # sin parametros no se interpretan los '%' del SQL
    return cur.fetchall() if cur.description else None
PREFIJO = "Test Fusion"
TOTAL_REAL = D("134946971.06")
FILAS = itertools.count(1)


def limpiar_datos_de_prueba(lote=None):
    if lote:
        consulta("DELETE FROM orden_linea WHERE lote_id = %s", (lote,))
    ids = {"cliente": [], "agencia": []}
    for ent in ids:
        ids[ent] = [f["id"] for f in consulta(f"SELECT id FROM {ent} WHERE nombre LIKE %s", (PREFIJO + "%",))]
        if ids[ent]:
            consulta("DELETE FROM sugerencia_fusion WHERE entidad = %s AND (nombre_id = ANY(%s) OR parecido_id = ANY(%s))",
                     (ent, ids[ent], ids[ent]))
            consulta(f"DELETE FROM {ent}_alias WHERE {ent}_id = ANY(%s)", (ids[ent],))
            if ent == "cliente":
                consulta("DELETE FROM alerta WHERE cliente_id = ANY(%s)", (ids[ent],))
            consulta(f"DELETE FROM {ent} WHERE id = ANY(%s)", (ids[ent],))
    consulta("DELETE FROM fusion_log WHERE absorbido_nombre LIKE %s OR sobreviviente_nombre LIKE %s",
             (PREFIJO + "%", PREFIJO + "%"))


class ConDatosDeFusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        limpiar_usuarios()
        consulta("DELETE FROM lote_importacion WHERE hash_archivo LIKE 'test-fusion-%'")
        limpiar_datos_de_prueba()
        cls.lote = consulta(
            "INSERT INTO lote_importacion (archivo, hash_archivo, fecha) VALUES ('test-fusion', %s, '2000-01-01') RETURNING id",
            ("test-fusion-" + secrets.token_hex(6),),
        )[0]["id"]
        cls.admin = cls.crear_usuario("administrador")
        cls.operador = cls.crear_usuario("operador")

    @staticmethod
    def crear_usuario(rol):
        email = email_de_prueba()
        uid = auth.crear_usuario(email, f"{rol.title()} de prueba", rol, password_aleatoria())
        consulta("UPDATE usuario SET debe_cambiar_password = FALSE WHERE id = %s", (uid,))
        return {"id": uid, "email": email, "nombre": f"{rol.title()} de prueba", "rol": rol, "debe_cambiar_password": False}

    @classmethod
    def tearDownClass(cls):
        limpiar_datos_de_prueba(cls.lote)
        consulta("DELETE FROM lote_importacion WHERE id = %s", (cls.lote,))
        limpiar_usuarios()

    def setUp(self):
        self.tag = secrets.token_hex(3)

    def tearDown(self):
        limpiar_datos_de_prueba(self.lote)

    # --- datos de prueba
    def nombre(self, base):
        return f"{PREFIJO} {base} {self.tag}"

    def cliente(self, base, tipo="privado"):
        nombre = self.nombre(base)
        cid = consulta("INSERT INTO cliente (nombre, tipo) VALUES (%s, %s) RETURNING id", (nombre, tipo))[0]["id"]
        consulta("INSERT INTO cliente_alias (alias_normalizado, cliente_id) VALUES (%s, %s)", (normalizar_nombre(nombre), cid))
        return cid

    def agencia(self, base):
        nombre = self.nombre(base)
        aid = consulta("INSERT INTO agencia (nombre) VALUES (%s) RETURNING id", (nombre,))[0]["id"]
        consulta("INSERT INTO agencia_alias (alias_normalizado, agencia_id) VALUES (%s, %s)", (normalizar_nombre(nombre), aid))
        return aid

    def linea(self, cliente_id, mes, neto, agencia_id=None):
        consulta(
            "INSERT INTO orden_linea (lote_id, hoja, fila_origen, anio, mes, tipo_venta, cliente_id, agencia_id, neto) "
            "VALUES (%s, 'Test', %s, 2026, %s, 'LOCAL_FACTURADO', %s, %s, %s)",
            (self.lote, next(FILAS), mes, cliente_id, agencia_id, neto),
        )

    def sugerencia(self, entidad, nombre_id, parecido_id, similitud="0.950", estado="abierta"):
        return consulta(
            "INSERT INTO sugerencia_fusion (lote_id, entidad, nombre_id, parecido_id, similitud, estado) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (self.lote, entidad, nombre_id, parecido_id, similitud, estado),
        )[0]["id"]

    # --- consultas de verificacion
    def existe(self, tabla, id_):
        return bool(consulta(f"SELECT 1 FROM {tabla} WHERE id = %s", (id_,)))

    def lineas_de(self, col, id_):
        return consulta(f"SELECT mes, neto FROM orden_linea WHERE lote_id = %s AND {col} = %s ORDER BY mes", (self.lote, id_))

    def alias_de(self, tabla, nombre):
        fila = consulta(f"SELECT {tabla}_id AS id FROM {tabla}_alias WHERE alias_normalizado = %s", (normalizar_nombre(nombre),))
        return fila[0]["id"] if fila else None

    def estado(self, sugerencia_id):
        fila = consulta("SELECT estado FROM sugerencia_fusion WHERE id = %s", (sugerencia_id,))
        return fila[0]["estado"] if fila else None

    def suma_global(self):
        return consulta("SELECT coalesce(sum(neto), 0) AS t FROM orden_linea")[0]["t"]


class UnionDeClientes(ConDatosDeFusion):
    def test_une_todo_en_una_transaccion_y_conserva_el_neto(self):
        a, b, z = self.cliente("A"), self.cliente("B"), self.cliente("Z")
        self.linea(a, 1, 100); self.linea(a, 2, 200); self.linea(b, 3, 50); self.linea(z, 4, 10)
        s_ba = self.sugerencia("cliente", b, a)
        s_bz = self.sugerencia("cliente", b, z)
        s_az = self.sugerencia("cliente", a, z)
        antes = self.suma_global()

        resultado = fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)

        self.assertEqual(self.suma_global(), antes)  # el neto total no cambia
        self.assertEqual(resultado["lineas_movidas"], 1)
        self.assertFalse(self.existe("cliente", b))  # la fila absorbida se borra
        self.assertEqual([(l["mes"], l["neto"]) for l in self.lineas_de("cliente_id", a)], [(1, 100), (2, 200), (3, 50)])
        self.assertEqual(self.lineas_de("cliente_id", z), [{"mes": 4, "neto": D("10.00")}])
        # alias: el nombre absorbido ahora lleva al sobreviviente
        self.assertEqual(self.alias_de("cliente", self.nombre("B")), a)
        self.assertEqual(self.alias_de("cliente", self.nombre("A")), a)
        # sugerencias: la del par queda fusionada; la de B con Z ya existia como A con Z, se borra la repetida
        self.assertEqual(self.estado(s_ba), "fusionada")
        self.assertIsNone(self.estado(s_bz))
        self.assertEqual(self.estado(s_az), "abierta")
        # registro
        log = consulta("SELECT * FROM fusion_log WHERE absorbido_id = %s", (b,))
        self.assertEqual(len(log), 1)
        self.assertEqual((log[0]["entidad"], log[0]["sobreviviente_id"], log[0]["lineas_movidas"]), ("cliente", a, 1))
        self.assertEqual((log[0]["absorbido_nombre"], log[0]["sobreviviente_nombre"]), (self.nombre("B"), self.nombre("A")))
        self.assertEqual((log[0]["usuario_id"], log[0]["usuario_email"]), (self.admin["id"], self.admin["email"]))
        self.assertIsNotNone(log[0]["fecha"])

    def test_las_sugerencias_de_terceros_pasan_al_sobreviviente(self):
        a, b, z = self.cliente("A"), self.cliente("B"), self.cliente("Z")
        s_bz = self.sugerencia("cliente", b, z, "0.920")
        fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        fila = consulta("SELECT nombre_id, parecido_id, similitud, estado FROM sugerencia_fusion WHERE id = %s", (s_bz,))[0]
        self.assertEqual((fila["nombre_id"], fila["parecido_id"], fila["estado"]), (a, z, "abierta"))
        self.assertEqual(fila["similitud"], D("0.920"))

    def test_tipos_distintos_piden_confirmacion_y_conservan_publica(self):
        for sobrevive_publica in (False, True):
            with self.subTest(sobrevive_publica=sobrevive_publica):
                a = self.cliente(f"A{sobrevive_publica}", "publica" if sobrevive_publica else "privado")
                b = self.cliente(f"B{sobrevive_publica}", "privado" if sobrevive_publica else "publica")
                self.linea(b, 1, 70)
                with self.assertRaises(fusion.ErrorFusion) as ctx:
                    fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
                self.assertTrue(ctx.exception.requiere_confirmacion)
                self.assertTrue(self.existe("cliente", b))  # sin confirmar no se toco nada
                self.assertEqual(len(self.lineas_de("cliente_id", b)), 1)
                fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a, confirmar_tipo_distinto=True)
                tipo = consulta("SELECT tipo FROM cliente WHERE id = %s", (a,))[0]["tipo"]
                self.assertEqual(tipo, "publica")  # se conserva 'publica' si alguno lo era

    def test_dos_privados_siguen_privados_sin_pedir_confirmacion(self):
        a, b = self.cliente("A"), self.cliente("B")
        fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        self.assertEqual(consulta("SELECT tipo FROM cliente WHERE id = %s", (a,))[0]["tipo"], "privado")

    def test_no_se_puede_unir_un_nombre_consigo_mismo_ni_uno_inexistente(self):
        a = self.cliente("A")
        with self.assertRaises(fusion.ErrorFusion):
            fusion.unir(self.admin, "cliente", absorbido_id=a, sobreviviente_id=a)
        with self.assertRaises(fusion.ErrorFusion):
            fusion.unir(self.admin, "cliente", absorbido_id=a, sobreviviente_id=2_000_000_000)
        with self.assertRaises(fusion.ErrorFusion):
            fusion.unir(self.admin, "producto", absorbido_id=a, sobreviviente_id=a + 1)

    def test_las_alertas_del_absorbido_pasan_al_sobreviviente(self):
        a, b = self.cliente("A"), self.cliente("B")
        consulta("INSERT INTO alerta (tipo, cliente_id, detalle) VALUES ('caida', %s, 'prueba')", (b,))
        fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        self.assertEqual(consulta("SELECT count(*) AS n FROM alerta WHERE cliente_id = %s", (a,))[0]["n"], 1)


class UnionDeAgencias(ConDatosDeFusion):
    def test_une_agencias(self):
        cliente = self.cliente("C")
        a1, a2 = self.agencia("Cordoba"), self.agencia("Cordoba Turismo")
        self.linea(cliente, 1, 100, a1); self.linea(cliente, 2, 40, a2); self.linea(cliente, 3, 60, a2)
        sug = self.sugerencia("agencia", a2, a1)
        antes = self.suma_global()
        resultado = fusion.unir(self.admin, "agencia", absorbido_id=a2, sobreviviente_id=a1)
        self.assertEqual(resultado["lineas_movidas"], 2)
        self.assertEqual(self.suma_global(), antes)
        self.assertFalse(self.existe("agencia", a2))
        self.assertEqual(len(self.lineas_de("agencia_id", a1)), 3)
        self.assertEqual(self.alias_de("agencia", self.nombre("Cordoba Turismo")), a1)
        self.assertEqual(self.estado(sug), "fusionada")
        self.assertEqual(consulta("SELECT entidad FROM fusion_log WHERE absorbido_id = %s", (a2,))[0]["entidad"], "agencia")


class Atomicidad(ConDatosDeFusion):
    def preparar(self):
        a, b = self.cliente("A"), self.cliente("B")
        self.linea(a, 1, 100); self.linea(b, 2, 50)
        return a, b, self.sugerencia("cliente", b, a)

    def verificar_sin_cambios(self, a, b, sug, antes):
        self.assertTrue(self.existe("cliente", b))
        self.assertEqual(len(self.lineas_de("cliente_id", b)), 1)
        self.assertEqual(len(self.lineas_de("cliente_id", a)), 1)
        self.assertEqual(self.alias_de("cliente", self.nombre("B")), b)
        self.assertEqual(self.estado(sug), "abierta")
        self.assertEqual(consulta("SELECT count(*) AS n FROM fusion_log WHERE absorbido_id = %s", (b,))[0]["n"], 0)
        self.assertEqual(self.suma_global(), antes)

    def test_si_falla_el_registro_no_queda_nada_a_medias(self):
        a, b, sug = self.preparar()
        antes = self.suma_global()
        with mock.patch("src.fusion._registrar_en_el_log", side_effect=RuntimeError("falla simulada")):
            with self.assertRaises(RuntimeError):
                fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        self.verificar_sin_cambios(a, b, sug, antes)

    def test_si_la_suma_de_netos_cambiara_no_se_une_nada(self):
        a, b, sug = self.preparar()
        antes = self.suma_global()
        with mock.patch("src.fusion._suma_de_netos", side_effect=[D(1), D(2)]):
            with self.assertRaises(fusion.ErrorFusion):
                fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        self.verificar_sin_cambios(a, b, sug, antes)


class SoloAdministradores(ConDatosDeFusion):
    def test_un_operador_no_puede_unir_ni_descartar(self):
        a, b = self.cliente("A"), self.cliente("B")
        sug = self.sugerencia("cliente", b, a)
        antes = self.suma_global()
        intentos = [
            self.operador,
            {**self.operador, "rol": "administrador"},  # la sesion dice admin, pero la base manda
            {"id": 2_000_000_000, "email": "no@existe", "nombre": "x", "rol": "administrador", "debe_cambiar_password": False},
        ]
        for usuario in intentos:
            with self.subTest(usuario=usuario["rol"], id=usuario["id"]):
                with self.assertRaises(fusion.ErrorFusion):
                    fusion.unir(usuario, "cliente", absorbido_id=b, sobreviviente_id=a)
                with self.assertRaises(fusion.ErrorFusion):
                    fusion.descartar_sugerencia(usuario, sug)
        self.assertTrue(self.existe("cliente", b))
        self.assertEqual(self.estado(sug), "abierta")
        self.assertEqual(self.suma_global(), antes)

    def test_un_administrador_desactivado_tampoco(self):
        a, b = self.cliente("A"), self.cliente("B")
        consulta("UPDATE usuario SET activo = FALSE WHERE id = %s", (self.admin["id"],))
        try:
            with self.assertRaises(fusion.ErrorFusion):
                fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        finally:
            consulta("UPDATE usuario SET activo = TRUE WHERE id = %s", (self.admin["id"],))
        self.assertTrue(self.existe("cliente", b))

    def test_el_menu_del_operador_no_incluye_la_pantalla(self):
        titulos_admin = [p["titulo"] for p in paginas_para(self.admin)]
        titulos_operador = [p["titulo"] for p in paginas_para(self.operador)]
        self.assertIn("Nombres duplicados", titulos_admin)
        self.assertNotIn("Nombres duplicados", titulos_operador)
        for comun in ("Tablero mensual", "Clientes por mes", "Conciliación contra el Excel"):
            self.assertIn(comun, titulos_operador)

    def test_descartar_sugerencia(self):
        a, b = self.cliente("A"), self.cliente("B")
        sug = self.sugerencia("cliente", b, a)
        fusion.descartar_sugerencia(self.admin, sug)
        self.assertEqual(self.estado(sug), "descartada")
        self.assertTrue(self.existe("cliente", b))  # descartar no une
        with self.assertRaises(fusion.ErrorFusion):
            fusion.descartar_sugerencia(self.admin, sug)  # ya no esta abierta


class Importador(ConDatosDeFusion):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        spec = importlib.util.spec_from_file_location("import_resumen", RAIZ / "scripts/import_resumen.py")
        cls.importador = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.importador)

    def resolver(self, entidad, crudo):
        """Resuelve un nombre como lo haria el importador, y devuelve (id, cantidad de filas de la entidad)."""
        with psycopg.connect(os.environ["DATABASE_URL"], options="-c default_transaction_read_only=on") as conn, conn.cursor() as cur:
            entidades = self.importador.Entidades(cur, entidad)
            resuelto = entidades.resolver(crudo, self.lote)  # si el alias existe no escribe nada
            cur.execute(f"SELECT count(*) FROM {entidad}")
            return resuelto, cur.fetchone()[0]

    def test_un_nombre_absorbido_se_resuelve_al_sobreviviente_por_alias(self):
        a, b = self.cliente("A"), self.cliente("B")
        fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)
        total = consulta("SELECT count(*) AS n FROM cliente")[0]["n"]
        variantes = [self.nombre("B"), self.nombre("B").upper(), "  " + self.nombre("B").replace(" ", "   ") + " "]
        for variante in variantes:
            with self.subTest(variante=variante):
                resuelto, cantidad = self.resolver("cliente", variante)
                self.assertEqual(resuelto, a)  # va al sobreviviente
                self.assertEqual(cantidad, total)  # y no se crea un cliente nuevo

    def test_lo_mismo_con_agencias(self):
        a1, a2 = self.agencia("Cordoba"), self.agencia("Cordoba Turismo")
        fusion.unir(self.admin, "agencia", absorbido_id=a2, sobreviviente_id=a1)
        resuelto, _ = self.resolver("agencia", self.nombre("Cordoba Turismo").lower())
        self.assertEqual(resuelto, a1)


class MarcasDeLaMatriz(ConDatosDeFusion):
    TIPOS = ["LOCAL_FACTURADO"]

    def matriz(self):
        filas = consultas.neto_por_cliente_y_mes(self.lote, 2026, None, self.TIPOS, None, "")
        return {c["id"]: c for c in armar_matriz(filas, [1, 2, 3, 4])["clientes"]}

    def test_se_perdio_nuevo_y_advertencia_se_actualizan(self):
        a, b = self.cliente("A"), self.cliente("B")
        for mes in (1, 2):
            self.linea(a, mes, 100)
        for mes in (3, 4):
            self.linea(b, mes, 100)
        self.sugerencia("cliente", b, a)
        st_clear()
        antes = self.matriz()
        self.assertEqual(antes[a]["marcas"], {3: "perdido"})   # A estaba y dejo de aparecer
        self.assertEqual(antes[b]["marcas"], {3: "nuevo"})     # B aparece de golpe
        self.assertTrue({a, b} <= consultas.clientes_con_sugerencia_abierta())  # ⚠ en los dos

        fusion.unir(self.admin, "cliente", absorbido_id=b, sobreviviente_id=a)  # limpia el cache

        despues = self.matriz()
        self.assertEqual(list(despues), [a])
        self.assertEqual(despues[a]["marcas"], {})              # ya no hay "se perdio" ni "nuevo"
        self.assertEqual(despues[a]["total"], D(400))
        self.assertFalse({a, b} & consultas.clientes_con_sugerencia_abierta())  # sin ⚠


def st_clear():
    import streamlit as st
    st.cache_data.clear()


class Pantalla(ConDatosDeFusion):
    def correr(self, usuario, **estado):
        at = AppTest.from_file(str(RAIZ / "pantallas/fusion.py"), default_timeout=120)
        for k, v in estado.items():
            at.session_state[k] = v
        with mock.patch("src.auth.sesion_actual", return_value=usuario):
            return at, at.run()

    def test_un_operador_no_puede_usar_la_pantalla(self):
        with mock.patch("src.consultas._consultar") as consultar:
            at, _ = self.correr(self.operador)
            self.assertEqual(len(at.exception), 0)
            self.assertEqual([e.value for e in at.error], ["Esta pantalla es solo para administradores."])
            self.assertEqual(len(at.button), 0)
            self.assertEqual(len(at.tabs), 0)
            consultar.assert_not_called()  # ni una consulta antes de cortar

    def test_sin_sesion_pide_login(self):
        at, _ = self.correr(None)
        self.assertEqual([t.value for t in at.title], ["Ingresar"])
        self.assertEqual(len(at.button), 1)  # solo el boton del formulario de login

    def test_el_administrador_ve_las_sugerencias_abiertas(self):
        at, _ = self.correr(self.admin)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([t.value for t in at.title], ["Nombres duplicados"])
        abiertas = len(consultas.sugerencias_con_ids("cliente"))
        self.assertEqual(len([b for b in at.button if b.label == "No es el mismo"]), abiertas)
        self.assertEqual(len(at.tabs), 3)

    def preparar_sugerencia(self, tipo_a="privado", tipo_b="privado"):
        a, b = self.cliente("A", tipo_a), self.cliente("B", tipo_b)
        self.linea(a, 1, 100); self.linea(b, 2, 50)
        sug = self.sugerencia("cliente", b, a, "0.999")  # la mas parecida: sale primera
        st_clear()
        return a, b, sug

    def test_unir_pide_confirmacion_y_cancelar_no_toca_nada(self):
        a, b, sug = self.preparar_sugerencia()
        at, _ = self.correr(self.admin)
        with mock.patch("src.auth.sesion_actual", return_value=self.admin):
            at.button(key=f"unir_{sug}_parecido").click().run()  # queda A, se absorbe B
            self.assertIn("Confirmá la unión", [s.value for s in at.subheader])
            self.assertTrue(self.existe("cliente", b))  # todavia nada escrito
            at.button(key="fusion_cancelar").click().run()
        self.assertNotIn("Confirmá la unión", [s.value for s in at.subheader])
        self.assertTrue(self.existe("cliente", b))
        self.assertEqual(self.estado(sug), "abierta")

    def test_confirmar_une_y_las_demas_pantallas_ven_el_cambio(self):
        a, b, sug = self.preparar_sugerencia()
        at, _ = self.correr(self.admin)
        with mock.patch("src.auth.sesion_actual", return_value=self.admin):
            at.button(key=f"unir_{sug}_parecido").click().run()
            at.button(key="fusion_confirmar").click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertFalse(self.existe("cliente", b))
        self.assertEqual(len(self.lineas_de("cliente_id", a)), 2)
        self.assertTrue(any(s.value.startswith("Listo:") for s in at.success))
        self.assertEqual(self.estado(sug), "fusionada")

    def test_tipos_distintos_muestran_la_advertencia(self):
        a, b, sug = self.preparar_sugerencia("privado", "publica")
        at, _ = self.correr(self.admin)
        with mock.patch("src.auth.sesion_actual", return_value=self.admin):
            at.button(key=f"unir_{sug}_parecido").click().run()  # absorbe B (publica) en A (privado)
            avisos = [w.value for w in at.warning]
            self.assertTrue(any("es pública" in w and "es privada" in w and "queda como pública" in w for w in avisos), avisos)
            at.button(key="fusion_confirmar").click().run()
        self.assertEqual(consulta("SELECT tipo FROM cliente WHERE id = %s", (a,))[0]["tipo"], "publica")

    def test_no_es_el_mismo_descarta_sin_unir(self):
        a, b, sug = self.preparar_sugerencia()
        at, _ = self.correr(self.admin)
        with mock.patch("src.auth.sesion_actual", return_value=self.admin):
            at.button(key=f"descartar_{sug}").click().run()
        self.assertEqual(self.estado(sug), "descartada")
        self.assertTrue(self.existe("cliente", b))


class NombreBase(unittest.TestCase):
    """Sin base de datos: como se arman los grupos 'Nombre' + 'Nombre (aclaratorio)'."""

    def filas(self, *nombres):
        return [{"id": i, "nombre": n, "tipo": "privado"} for i, n in enumerate(nombres, 1)]

    def test_nombre_base_saca_el_parentesis_del_final(self):
        self.assertEqual(fusion.nombre_base("Yuhmak (Campaña Seg. Vial)"), "yuhmak")
        self.assertEqual(fusion.nombre_base("  YUHMAK  (entrevistas) "), "yuhmak")
        self.assertEqual(fusion.nombre_base("Yuhmak"), "yuhmak")
        self.assertEqual(fusion.nombre_base("Alar SA / Tucumán Alambres"), "alar sa / tucuman alambres")

    def test_yuhmak_se_sugiere_como_un_solo_grupo(self):
        filas = self.filas("Yuhmak (entrevistas)", "Yuhmak", "Otro SA", "Yuhmak (Automoviles)",
                           "Yuhmak (Campaña Seg. Vial)")
        grupos = fusion.grupos_por_nombre_base(filas)
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["base"]["nombre"], "Yuhmak")
        self.assertEqual([v["nombre"] for v in grupos[0]["variantes"]],
                         ["Yuhmak (Automoviles)", "Yuhmak (Campaña Seg. Vial)", "Yuhmak (entrevistas)"])

    def test_sin_el_nombre_base_o_sin_variantes_no_hay_grupo(self):
        self.assertEqual(fusion.grupos_por_nombre_base(self.filas("Municipalidad Lules (Expo Lules)")), [])
        self.assertEqual(fusion.grupos_por_nombre_base(self.filas("Yuhmak (a)", "Yuhmak (b)")), [])
        self.assertEqual(fusion.grupos_por_nombre_base(self.filas("Yuhmak", "Otro")), [])


class UnionDeGrupo(ConDatosDeFusion):
    """El caso Yuhmak con datos de prueba: un nombre base y tres variantes con parentesis."""

    def preparar(self):
        base = self.cliente("Yuhmak")
        variantes = []
        for k, (aclaratorio, mes, neto) in enumerate(
                [("Automoviles", 1, "1099173.53"), ("Campaña Seg. Vial", 2, "2045454.57"), ("entrevistas", 3, "132231.40")]):
            nombre = f"{self.nombre('Yuhmak')} ({aclaratorio})"
            vid = consulta("INSERT INTO cliente (nombre) VALUES (%s) RETURNING id", (nombre,))[0]["id"]
            consulta("INSERT INTO cliente_alias (alias_normalizado, cliente_id) VALUES (%s, %s)", (normalizar_nombre(nombre), vid))
            self.linea(vid, mes, neto)
            variantes.append((vid, nombre))
        self.linea(base, 4, "1632231.41")
        return base, variantes

    def test_une_el_grupo_sin_cambiar_totales_y_deja_los_nombres_como_alias(self):
        base, variantes = self.preparar()
        antes, antes_grupo = self.suma_global(), D("1632231.41") + D("1099173.53") + D("2045454.57") + D("132231.40")
        r = fusion.unir_grupo(self.admin, "cliente", base, [v for v, _ in variantes])
        self.assertEqual(self.suma_global(), antes)
        self.assertEqual(sum(l["neto"] for l in self.lineas_de("cliente_id", base)), antes_grupo)
        self.assertEqual(len(self.lineas_de("cliente_id", base)), 4)
        self.assertEqual(r["lineas_movidas"], 3)
        for vid, nombre in variantes:
            self.assertFalse(self.existe("cliente", vid))
            self.assertEqual(self.alias_de("cliente", nombre), base)
        self.assertEqual(self.alias_de("cliente", self.nombre("Yuhmak")), base)
        self.assertEqual(consulta("SELECT count(*) AS n FROM fusion_log WHERE sobreviviente_id = %s", (base,))[0]["n"], 3)

    def test_si_un_nombre_no_es_del_grupo_no_se_une_ninguno(self):
        base, variantes = self.preparar()
        ajeno = self.cliente("Otro cliente")
        antes = self.suma_global()
        with self.assertRaises(fusion.ErrorFusion):
            fusion.unir_grupo(self.admin, "cliente", base, [variantes[0][0], ajeno])
        self.assertTrue(self.existe("cliente", variantes[0][0]))
        self.assertTrue(self.existe("cliente", ajeno))
        self.assertEqual(self.suma_global(), antes)

    def test_si_falla_uno_no_queda_a_medias(self):
        base, variantes = self.preparar()
        with mock.patch("src.fusion._registrar_en_el_log", side_effect=[None, RuntimeError("falla")]):
            with self.assertRaises(RuntimeError):
                fusion.unir_grupo(self.admin, "cliente", base, [v for v, _ in variantes])
        for vid, _ in variantes:
            self.assertTrue(self.existe("cliente", vid))
        self.assertEqual(len(self.lineas_de("cliente_id", base)), 1)

    def test_un_operador_no_puede_unir_un_grupo(self):
        base, variantes = self.preparar()
        with self.assertRaises(fusion.ErrorFusion):
            fusion.unir_grupo(self.operador, "cliente", base, [v for v, _ in variantes])
        self.assertTrue(all(self.existe("cliente", v) for v, _ in variantes))

    def test_la_pantalla_sugiere_el_grupo_y_une_con_confirmacion(self):
        base, variantes = self.preparar()
        st_clear()
        at = AppTest.from_file(str(RAIZ / "pantallas/fusion.py"), default_timeout=120)
        with mock.patch("src.auth.sesion_actual", return_value=self.admin):
            at.run()
            self.assertEqual(len(at.exception), 0)
            self.assertIn("Mismo nombre con variantes entre paréntesis", [s.value for s in at.subheader])
            boton = at.button(key=f"unir_grupo_{base}")
            self.assertIn("Unir los 4 en", boton.label)
            boton.click().run()
            self.assertTrue(all(self.existe("cliente", v) for v, _ in variantes))  # falta confirmar
            at.button(key="fusion_confirmar").click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertFalse(any(self.existe("cliente", v) for v, _ in variantes))
        self.assertTrue(any("3 nombres se unieron" in s.value for s in at.success))


class YuhmakRealSoloLectura(unittest.TestCase):
    """Con los datos reales de la base de testing, SIN escribir: solo se consulta."""

    def test_los_cuatro_yuhmak_se_sugieren_como_un_grupo(self):
        carga = consultas.ultima_carga()
        if carga is None:
            self.skipTest("No hay ninguna carga en la base.")
        resumen = consultas.resumen_de_entidades("cliente", carga["id"])
        yuhmak = [g for g in fusion.grupos_por_nombre_base(resumen) if g["base"]["nombre"] == "Yuhmak"]
        if not yuhmak:
            self.skipTest("Los Yuhmak ya se unieron (o no estan cargados).")
        self.assertEqual(len(yuhmak), 1)
        self.assertEqual([v["nombre"] for v in yuhmak[0]["variantes"]],
                         ["Yuhmak (Automoviles)", "Yuhmak (Campaña Seg. Vial)", "Yuhmak (entrevistas)"])
        total = yuhmak[0]["base"]["neto"] + sum(v["neto"] for v in yuhmak[0]["variantes"])
        self.assertEqual(total, D("4909090.91"))  # lo que sumaria "Yuhmak" despues de unir


if __name__ == "__main__":
    unittest.main()
