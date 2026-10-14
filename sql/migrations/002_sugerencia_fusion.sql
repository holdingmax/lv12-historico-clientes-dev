-- 002_sugerencia_fusion.sql
-- Reemplaza nombre_pendiente: el importador ahora carga siempre todas las lineas y crea cada
-- cliente/agencia con el nombre tal como viene. Cuando un nombre nuevo se parece (similitud
-- >= 0,9) a uno existente, se registra una sugerencia de fusion para revisar desde pantalla.
-- Las sugerencias no afectan las lineas ni los totales.

DROP TABLE nombre_pendiente;

CREATE TABLE sugerencia_fusion (
    id           SERIAL PRIMARY KEY,
    lote_id      INTEGER NOT NULL REFERENCES lote_importacion(id) ON DELETE CASCADE,
    entidad      TEXT NOT NULL CHECK (entidad IN ('cliente', 'agencia')),
    nombre_id    INTEGER NOT NULL,          -- cliente/agencia recien creado (segun entidad)
    parecido_id  INTEGER NOT NULL,          -- cliente/agencia existente al que se parece
    similitud    NUMERIC(4,3) NOT NULL CHECK (similitud BETWEEN 0 AND 1),
    estado       TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'fusionada', 'descartada')),
    CHECK (nombre_id <> parecido_id)
);

CREATE UNIQUE INDEX sugerencia_fusion_uq ON sugerencia_fusion (entidad, nombre_id, parecido_id);
