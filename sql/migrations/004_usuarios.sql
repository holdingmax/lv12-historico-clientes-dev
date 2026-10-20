-- 004_usuarios.sql
-- Login propio de la herramienta: usuarios, roles y registro de accesos.
-- Cada herramienta del Holding tiene su propio login y sus propios usuarios (Toolbox es solo
-- la puerta de entrada, no maneja credenciales). Nunca se guarda una contrasena en claro:
-- solo el hash (bcrypt). El registro de accesos tampoco guarda contrasenas.

CREATE TABLE usuario (
    id                     SERIAL PRIMARY KEY,
    email                  TEXT NOT NULL UNIQUE CHECK (email = lower(email)),  -- siempre en minusculas
    nombre                 TEXT NOT NULL,
    password_hash          TEXT NOT NULL,
    rol                    TEXT NOT NULL CHECK (rol IN ('administrador', 'operador')),
    activo                 BOOLEAN NOT NULL DEFAULT TRUE,
    debe_cambiar_password  BOOLEAN NOT NULL DEFAULT TRUE,   -- TRUE al crear: la clave inicial es temporal
    intentos_fallidos      INTEGER NOT NULL DEFAULT 0,      -- fallos seguidos; 5 bloquean el acceso
    bloqueado_hasta        TIMESTAMPTZ,                     -- NULL = no bloqueado
    ultimo_acceso          TIMESTAMPTZ,
    creado_en              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE acceso_log (
    id               BIGSERIAL PRIMARY KEY,
    usuario_id       INTEGER REFERENCES usuario(id) ON DELETE SET NULL,  -- NULL si el email no existe
    email_intentado  TEXT NOT NULL,
    fecha            TIMESTAMPTZ NOT NULL DEFAULT now(),
    resultado        TEXT NOT NULL CHECK (resultado IN ('ok', 'fallo', 'bloqueado'))
);

CREATE INDEX acceso_log_usuario_ix ON acceso_log (usuario_id, fecha DESC);
CREATE INDEX acceso_log_fecha_ix ON acceso_log (fecha DESC);
