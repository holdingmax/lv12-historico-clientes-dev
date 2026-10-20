"""Pruebas del login: hash, bloqueo, mensaje unico y acceso a las pantallas.

Usan la base de testing (DATABASE_URL en .env). Crean usuarios descartables con email
test-auth-*@example.invalid y contrasenas aleatorias generadas en cada corrida, y los borran al
terminar (junto con sus registros de acceso). Nunca tocan usuarios reales.
    python -m unittest discover -s tests -t .
"""
import contextlib
import importlib.util
import io
import secrets
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import auth  # noqa: E402

PATRON_EMAIL = "test-auth-%@example.invalid"
PANTALLAS = ["pantallas/tablero.py", "pantallas/clientes_mes.py", "pantallas/conciliacion.py"]


def password_aleatoria() -> str:
    return secrets.token_urlsafe(16)  # 22 caracteres, distinta en cada corrida


def email_de_prueba() -> str:
    return f"test-auth-{secrets.token_hex(6)}@example.invalid"


def consulta(sql, params=()):
    with auth._conexion_escritura() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def limpiar():
    consulta("DELETE FROM acceso_log WHERE email_intentado LIKE %s", (PATRON_EMAIL,))
    consulta("DELETE FROM usuario WHERE email LIKE %s", (PATRON_EMAIL,))


class HashYPolitica(unittest.TestCase):
    """Sin base de datos."""

    def test_hash_verifica_y_no_contiene_la_contrasena(self):
        p = password_aleatoria()
        h = auth.hashear_password(p)
        self.assertTrue(h.startswith("$2"))  # bcrypt
        self.assertNotIn(p, h)
        self.assertTrue(auth.verificar_password(p, h))
        self.assertFalse(auth.verificar_password(p + "x", h))

    def test_cada_hash_lleva_su_propia_sal(self):
        p = password_aleatoria()
        self.assertNotEqual(auth.hashear_password(p), auth.hashear_password(p))

    def test_politica_de_contrasenas(self):
        self.assertIsNotNone(auth.validar_password_nueva("a" * 9))
        self.assertIsNone(auth.validar_password_nueva("a" * 10))
        self.assertIsNotNone(auth.validar_password_nueva("a" * 73))  # limite de bcrypt

    def test_contrasena_demasiado_larga_no_rompe_el_login(self):
        h = auth.hashear_password(password_aleatoria())
        self.assertFalse(auth.verificar_password("a" * 200, h))

    def test_email_en_minusculas(self):
        self.assertEqual(auth.normalizar_email("  Ana@Radio.COM "), "ana@radio.com")


class ConBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        limpiar()

    @classmethod
    def tearDownClass(cls):
        limpiar()

    def nuevo_usuario(self, debe_cambiar=False, activo=True, rol="operador"):
        email, password = email_de_prueba(), password_aleatoria()
        uid = auth.crear_usuario(email, "Usuario de prueba", rol, password)
        consulta("UPDATE usuario SET debe_cambiar_password = %s, activo = %s WHERE id = %s",
                 (debe_cambiar, activo, uid))
        return email, password, uid

    def resultados(self, email):
        filas = consulta("SELECT resultado FROM acceso_log WHERE email_intentado = %s ORDER BY id", (email,))
        return [f["resultado"] for f in filas]


class LoginYBloqueo(ConBase):
    def test_crear_usuario_queda_con_cambio_obligatorio_y_email_en_minusculas(self):
        email, password = email_de_prueba().upper().replace("EXAMPLE.INVALID", "example.invalid"), password_aleatoria()
        uid = auth.crear_usuario(email, "Ana", "administrador", password)
        fila = consulta("SELECT * FROM usuario WHERE id = %s", (uid,))[0]
        self.assertEqual(fila["email"], email.lower())
        self.assertTrue(fila["debe_cambiar_password"])
        self.assertNotIn(password, fila["password_hash"])
        with self.assertRaises(auth.ErrorAuth):
            auth.crear_usuario(email, "Ana de nuevo", "operador", password)  # email repetido

    def test_login_correcto_y_contador_se_reinicia(self):
        email, password, uid = self.nuevo_usuario()
        for _ in range(4):
            self.assertIsNone(auth.autenticar(email, password + "mal"))
        usuario = auth.autenticar(email, password)
        self.assertEqual(usuario["id"], uid)
        self.assertNotIn("password_hash", usuario)
        fila = consulta("SELECT intentos_fallidos, bloqueado_hasta, ultimo_acceso FROM usuario WHERE id = %s", (uid,))[0]
        self.assertEqual(fila["intentos_fallidos"], 0)
        self.assertIsNone(fila["bloqueado_hasta"])
        self.assertIsNotNone(fila["ultimo_acceso"])
        self.assertEqual(self.resultados(email), ["fallo"] * 4 + ["ok"])

    def test_cinco_fallos_seguidos_bloquean_aunque_despues_ponga_la_correcta(self):
        email, password, uid = self.nuevo_usuario()
        for _ in range(auth.MAX_INTENTOS):
            self.assertIsNone(auth.autenticar(email, password + "mal"))
        bloqueado = consulta("SELECT bloqueado_hasta > now() AS b, bloqueado_hasta - now() AS resta FROM usuario WHERE id = %s", (uid,))[0]
        self.assertTrue(bloqueado["b"])
        self.assertGreater(bloqueado["resta"].total_seconds(), 14 * 60)
        self.assertLessEqual(bloqueado["resta"].total_seconds(), 15 * 60)
        # Con la contrasena correcta tampoco entra mientras dura el bloqueo.
        self.assertIsNone(auth.autenticar(email, password))
        self.assertEqual(self.resultados(email), ["fallo"] * 5 + ["bloqueado"])
        # Vencido el bloqueo, vuelve a entrar.
        consulta("UPDATE usuario SET bloqueado_hasta = now() - interval '1 minute' WHERE id = %s", (uid,))
        self.assertIsNotNone(auth.autenticar(email, password))

    def test_cuatro_fallos_no_bloquean(self):
        email, password, uid = self.nuevo_usuario()
        for _ in range(auth.MAX_INTENTOS - 1):
            auth.autenticar(email, password + "mal")
        self.assertIsNotNone(auth.autenticar(email, password))

    def test_usuario_inactivo_no_entra(self):
        email, password, _ = self.nuevo_usuario(activo=False)
        self.assertIsNone(auth.autenticar(email, password))

    def test_el_registro_de_accesos_no_guarda_contrasenas(self):
        email, password, _ = self.nuevo_usuario()
        auth.autenticar(email, password + "mal")
        auth.autenticar(email, password)
        filas = consulta("SELECT * FROM acceso_log WHERE email_intentado = %s", (email,))
        self.assertEqual(len(filas), 2)
        for fila in filas:
            self.assertNotIn(password, " ".join(str(v) for v in fila.values()))
        columnas = {r["column_name"] for r in consulta(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'acceso_log'")}
        self.assertEqual(columnas, {"id", "usuario_id", "email_intentado", "fecha", "resultado"})

    def test_email_inexistente_queda_en_el_registro_sin_usuario(self):
        email = email_de_prueba()
        self.assertIsNone(auth.autenticar(email, password_aleatoria()))
        fila = consulta("SELECT usuario_id, resultado FROM acceso_log WHERE email_intentado = %s", (email,))[0]
        self.assertIsNone(fila["usuario_id"])
        self.assertEqual(fila["resultado"], "fallo")

    def test_cambio_de_contrasena(self):
        email, password, uid = self.nuevo_usuario(debe_cambiar=True)
        nueva = password_aleatoria()
        with self.assertRaises(auth.ErrorAuth):
            auth.cambiar_password(uid, password + "mal", nueva)  # actual incorrecta
        with self.assertRaises(auth.ErrorAuth):
            auth.cambiar_password(uid, password, "corta")  # menos de 10
        with self.assertRaises(auth.ErrorAuth):
            auth.cambiar_password(uid, password, password)  # igual a la actual
        auth.cambiar_password(uid, password, nueva)
        self.assertFalse(consulta("SELECT debe_cambiar_password FROM usuario WHERE id = %s", (uid,))[0]["debe_cambiar_password"])
        self.assertIsNone(auth.autenticar(email, password))
        self.assertIsNotNone(auth.autenticar(email, nueva))


class MensajeUnico(ConBase):
    def intento_en_pantalla(self, email, password):
        at = AppTest.from_file(str(RAIZ / "pantallas/login.py"), default_timeout=60).run()
        at.text_input[0].set_value(email)
        at.text_input[1].set_value(password)
        at.button[0].click().run()
        return at

    def test_no_distingue_email_inexistente_de_contrasena_mala(self):
        email, password, _ = self.nuevo_usuario()
        existente_mal = self.intento_en_pantalla(email, password + "mal")
        inexistente = self.intento_en_pantalla(email_de_prueba(), password)
        self.assertEqual([e.value for e in existente_mal.error], [auth.MENSAJE_LOGIN_INCORRECTO])
        self.assertEqual([e.value for e in inexistente.error], [auth.MENSAJE_LOGIN_INCORRECTO])
        self.assertNotIn(auth.CLAVE_USUARIO, existente_mal.session_state)
        self.assertNotIn(auth.CLAVE_USUARIO, inexistente.session_state)

    def test_cuenta_bloqueada_muestra_el_mismo_mensaje(self):
        email, password, _ = self.nuevo_usuario()
        for _ in range(auth.MAX_INTENTOS):
            auth.autenticar(email, password + "mal")
        bloqueada = self.intento_en_pantalla(email, password)  # contrasena correcta, pero bloqueada
        self.assertEqual([e.value for e in bloqueada.error], [auth.MENSAJE_LOGIN_INCORRECTO])
        self.assertNotIn(auth.CLAVE_USUARIO, bloqueada.session_state)

    def test_login_correcto_abre_sesion(self):
        email, password, uid = self.nuevo_usuario()
        at = self.intento_en_pantalla(email, password)
        self.assertEqual(at.session_state[auth.CLAVE_USUARIO]["id"], uid)
        self.assertEqual(len(at.error), 0)


class AccesoALasPantallas(ConBase):
    def con_sesion(self, archivo, uid, email, debe_cambiar=False, actividad=None, revalidado=None):
        at = AppTest.from_file(str(RAIZ / archivo), default_timeout=120)
        ahora = time.time()
        at.session_state[auth.CLAVE_USUARIO] = {
            "id": uid, "email": email, "nombre": "Usuario de prueba", "rol": "operador",
            "debe_cambiar_password": debe_cambiar,
        }
        at.session_state[auth.CLAVE_ACTIVIDAD] = ahora if actividad is None else actividad
        at.session_state[auth.CLAVE_REVALIDADO] = ahora if revalidado is None else revalidado
        return at

    def assert_solo_login(self, at):
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([t.value for t in at.title], ["Ingresar"])
        self.assertEqual(len(at.metric), 0)
        self.assertFalse(any("<table" in m.value or "| Tipo de venta" in m.value for m in at.markdown))
        self.assertIn("Contraseña", [t.label for t in at.text_input])

    def test_sin_sesion_ninguna_pantalla_consulta_ni_muestra_datos(self):
        for archivo in PANTALLAS:
            with self.subTest(pantalla=archivo), mock.patch("src.consultas._consultar") as consultar:
                at = AppTest.from_file(str(RAIZ / archivo), default_timeout=60).run()
                self.assert_solo_login(at)
                consultar.assert_not_called()  # require_login corta antes de cualquier consulta

    def test_app_sin_sesion_muestra_solo_el_login(self):
        with mock.patch("src.consultas._consultar") as consultar:
            at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60).run()
            self.assert_solo_login(at)
            consultar.assert_not_called()

    def test_con_cambio_de_contrasena_pendiente_no_se_ve_ninguna_pantalla(self):
        email, _, uid = self.nuevo_usuario(debe_cambiar=True)
        for archivo in PANTALLAS + ["app.py"]:
            with self.subTest(pantalla=archivo), mock.patch("src.consultas._consultar") as consultar:
                at = self.con_sesion(archivo, uid, email, debe_cambiar=True).run()
                self.assertEqual(len(at.exception), 0)
                self.assertEqual([t.value for t in at.title], ["Elegí tu contraseña"])
                self.assertEqual(len(at.metric), 0)
                consultar.assert_not_called()

    def test_con_sesion_valida_se_ven_los_datos(self):
        email, _, uid = self.nuevo_usuario()
        at = self.con_sesion("pantallas/tablero.py", uid, email).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([t.value for t in at.title], ["Tablero mensual"])
        self.assertGreater(len(at.metric), 0)

    def test_app_con_sesion_muestra_navegacion_y_barra_lateral(self):
        email, _, uid = self.nuevo_usuario()
        at = self.con_sesion("app.py", uid, email).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([t.value for t in at.title], ["Tablero mensual"])
        barra = " ".join(m.value for m in at.sidebar.markdown) + " ".join(c.value for c in at.sidebar.caption)
        self.assertIn("Usuario de prueba", barra)
        self.assertIn("Operador", barra)
        self.assertEqual([b.label for b in at.sidebar.button], ["Cerrar sesión"])

    def test_cerrar_sesion_vuelve_al_login(self):
        email, _, uid = self.nuevo_usuario()
        at = self.con_sesion("app.py", uid, email).run()
        at.sidebar.button[0].click().run()
        self.assertNotIn(auth.CLAVE_USUARIO, at.session_state)
        self.assert_solo_login(at)

    def test_la_sesion_vence_a_los_60_minutos_sin_actividad(self):
        email, _, uid = self.nuevo_usuario()
        pasada = time.time() - (auth.INACTIVIDAD_SEGUNDOS + 60)
        for archivo in PANTALLAS:
            with self.subTest(pantalla=archivo), mock.patch("src.consultas._consultar") as consultar:
                at = self.con_sesion(archivo, uid, email, actividad=pasada).run()
                self.assert_solo_login(at)
                self.assertNotIn(auth.CLAVE_USUARIO, at.session_state)
                consultar.assert_not_called()
        # Un poco antes del limite sigue vigente.
        casi = time.time() - (auth.INACTIVIDAD_SEGUNDOS - 120)
        at = self.con_sesion("pantallas/tablero.py", uid, email, actividad=casi).run()
        self.assertEqual([t.value for t in at.title], ["Tablero mensual"])

    def test_usuario_desactivado_pierde_la_sesion(self):
        email, _, uid = self.nuevo_usuario()
        consulta("UPDATE usuario SET activo = FALSE WHERE id = %s", (uid,))
        # La revalidacion contra la base ya esta vencida: tiene que sacarlo.
        at = self.con_sesion("pantallas/tablero.py", uid, email, revalidado=0).run()
        self.assert_solo_login(at)
        self.assertNotIn(auth.CLAVE_USUARIO, at.session_state)


class ScriptCrearUsuario(ConBase):
    def test_crea_el_usuario_sin_imprimir_la_contrasena(self):
        spec = importlib.util.spec_from_file_location("crear_usuario", RAIZ / "scripts/crear_usuario.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        email, password = email_de_prueba(), password_aleatoria()
        salida = io.StringIO()
        with mock.patch("builtins.input", side_effect=[email.upper(), "Persona de prueba", "otro", "administrador"]), \
                mock.patch("getpass.getpass", side_effect=[password, password]), \
                contextlib.redirect_stdout(salida):
            codigo = modulo.main()
        self.assertEqual(codigo, 0)
        self.assertNotIn(password, salida.getvalue())
        fila = consulta("SELECT * FROM usuario WHERE email = %s", (email.lower(),))[0]
        self.assertEqual(fila["rol"], "administrador")
        self.assertTrue(fila["debe_cambiar_password"])
        self.assertTrue(auth.verificar_password(password, fila["password_hash"]))


if __name__ == "__main__":
    unittest.main()
