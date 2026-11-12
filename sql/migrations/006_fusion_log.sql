-- 006_fusion_log.sql
-- Registro de las uniones de nombres duplicados (pantalla "Nombres duplicados", solo
-- administradores). Unir es irreversible: la fila absorbida se borra y sus lineas pasan al que
-- sobrevive, asi que aca queda el rastro completo. Los ids y nombres se guardan como copia
-- (sin clave foranea) porque la fila absorbida ya no existe.

CREATE TABLE fusion_log (
    id                    SERIAL PRIMARY KEY,
    entidad               TEXT NOT NULL CHECK (entidad IN ('cliente', 'agencia')),
    absorbido_id          INTEGER NOT NULL,      -- el que se borro
    absorbido_nombre      TEXT NOT NULL,
    sobreviviente_id      INTEGER NOT NULL,      -- el que quedo
    sobreviviente_nombre  TEXT NOT NULL,
    lineas_movidas        INTEGER NOT NULL,      -- lineas de orden_linea que pasaron al sobreviviente
    usuario_id            INTEGER REFERENCES usuario(id) ON DELETE SET NULL,
    usuario_email         TEXT NOT NULL,         -- copia: sigue sirviendo si se borra el usuario
    fecha                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX fusion_log_fecha_ix ON fusion_log (fecha DESC);
