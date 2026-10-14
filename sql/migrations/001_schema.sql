-- 001_schema.sql
-- Esquema base: historico y evolucion de facturacion a clientes (Radio LV12).
-- Fuente: Resumen de Publicidades (hojas mensuales). El Excel es solo puerta de entrada.
-- Una migracion aplicada no se edita: los cambios van en una migracion nueva.
-- Cobranzas y tarifas quedan para la 002.

-- Categorias del Excel (cada bloque de las hojas mensuales)
CREATE TABLE tipo_venta (
    codigo      TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    factura     BOOLEAN NOT NULL,           -- TRUE si se factura
    es_canje    BOOLEAN NOT NULL DEFAULT FALSE,
    orden       INTEGER NOT NULL            -- orden de aparicion en pantallas
);

INSERT INTO tipo_venta (codigo, nombre, factura, es_canje, orden) VALUES
    ('AGENCIA',             'Agencias',             TRUE,  FALSE, 1),
    ('LOCAL_FACTURADO',     'Local facturado',      TRUE,  FALSE, 2),
    ('LOCAL_SIN_FACTURAR',  'Local sin facturar',   FALSE, FALSE, 3),
    ('COPRODUCCION',        'Coproducciones',       TRUE,  FALSE, 4),
    ('CANJE_FACTURADO',     'Canjes facturados',    TRUE,  TRUE,  5),
    ('CANJE_SIN_FACTURAR',  'Canjes sin facturar',  FALSE, TRUE,  6);

CREATE TABLE emisora (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE agencia (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    activa  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE agencia_alias (
    alias_normalizado TEXT PRIMARY KEY,     -- minusculas, sin tildes, espacios simples
    agencia_id        INTEGER NOT NULL REFERENCES agencia(id)
);

CREATE TABLE cliente (
    id        SERIAL PRIMARY KEY,
    nombre    TEXT NOT NULL UNIQUE,
    -- Regla de pauta publica pendiente de confirmar con Maxi: por ahora se marca desde pantalla.
    tipo      TEXT NOT NULL DEFAULT 'privado' CHECK (tipo IN ('privado', 'publica')),
    vendedor  TEXT,
    activo    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE cliente_alias (
    alias_normalizado TEXT PRIMARY KEY,
    cliente_id        INTEGER NOT NULL REFERENCES cliente(id)
);

-- Cada archivo importado
CREATE TABLE lote_importacion (
    id                 SERIAL PRIMARY KEY,
    archivo            TEXT NOT NULL,
    hash_archivo       TEXT NOT NULL,       -- mismo contenido no se vuelve a cargar
    usuario            TEXT,
    fecha              TIMESTAMPTZ NOT NULL DEFAULT now(),
    filas_ok           INTEGER NOT NULL DEFAULT 0,
    filas_rechazadas   INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX lote_hash_uq ON lote_importacion (hash_archivo);

-- Filas que el importador no acepto, con el motivo
CREATE TABLE fila_rechazada (
    id         SERIAL PRIMARY KEY,
    lote_id    INTEGER NOT NULL REFERENCES lote_importacion(id) ON DELETE CASCADE,
    hoja       TEXT NOT NULL,
    fila       INTEGER NOT NULL,
    motivo     TEXT NOT NULL,
    contenido  TEXT
);

-- Nombres que aparecieron en el Excel y todavia no se asignaron a un cliente/agencia.
-- Mientras estan pendientes, sus lineas no cuentan en los totales.
CREATE TABLE nombre_pendiente (
    id         SERIAL PRIMARY KEY,
    lote_id    INTEGER NOT NULL REFERENCES lote_importacion(id) ON DELETE CASCADE,
    entidad    TEXT NOT NULL CHECK (entidad IN ('cliente', 'agencia')),
    nombre     TEXT NOT NULL,
    resuelto   BOOLEAN NOT NULL DEFAULT FALSE
);

-- Una fila del Excel: un cliente, un periodo, una emisora, un importe
CREATE TABLE orden_linea (
    id             SERIAL PRIMARY KEY,
    lote_id        INTEGER NOT NULL REFERENCES lote_importacion(id) ON DELETE CASCADE,
    hoja           TEXT NOT NULL,
    fila_origen    INTEGER NOT NULL,
    anio           SMALLINT NOT NULL,
    mes            SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    periodo_texto  TEXT,                    -- tal como vino en el Excel
    tipo_venta     TEXT NOT NULL REFERENCES tipo_venta(codigo),
    cliente_id     INTEGER NOT NULL REFERENCES cliente(id),
    agencia_id     INTEGER REFERENCES agencia(id),   -- solo en bloque Agencias
    emisora_id     INTEGER REFERENCES emisora(id),
    op             TEXT,                    -- puede faltar
    vendedor       TEXT,
    factura_nro    TEXT,
    neto           NUMERIC(14,2) NOT NULL,
    total_con_iva  NUMERIC(14,2),
    UNIQUE (lote_id, hoja, fila_origen)
);
CREATE INDEX orden_linea_periodo_ix ON orden_linea (anio, mes);
CREATE INDEX orden_linea_cliente_ix ON orden_linea (cliente_id, anio, mes);

-- Totales del Excel por mes y tipo, para comparar contra la base
CREATE TABLE control_total_excel (
    lote_id     INTEGER NOT NULL REFERENCES lote_importacion(id) ON DELETE CASCADE,
    anio        SMALLINT NOT NULL,
    mes         SMALLINT NOT NULL,
    tipo_venta  TEXT NOT NULL REFERENCES tipo_venta(codigo),
    neto        NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (lote_id, anio, mes, tipo_venta)
);

CREATE TABLE alerta (
    id          SERIAL PRIMARY KEY,
    tipo        TEXT NOT NULL CHECK (tipo IN ('caida', 'sin_actividad', 'crecimiento', 'nombre_nuevo')),
    cliente_id  INTEGER REFERENCES cliente(id),
    anio        SMALLINT,
    mes         SMALLINT,
    detalle     TEXT,
    estado      TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'revisada')),
    creada      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Usuarios y roles: se definen con Toolbox (pendiente), no se crean tablas aca.
