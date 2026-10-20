-- 003_colapsar_espacios_nombres.sql
-- El importador ahora guarda emisoras, clientes y agencias con los espacios multiples
-- colapsados a uno solo. Esta correccion hace lo mismo con lo ya cargado.
-- Solo se renombra una fila si el nombre limpio no lo usa otra fila (el nombre es UNIQUE),
-- asi nunca se duplican ni se pisan registros; las lineas siguen apuntando al mismo id.

UPDATE emisora e
SET nombre = btrim(regexp_replace(e.nombre, '\s+', ' ', 'g'))
WHERE e.nombre <> btrim(regexp_replace(e.nombre, '\s+', ' ', 'g'))
  AND NOT EXISTS (
      SELECT 1 FROM emisora o
      WHERE o.id <> e.id AND o.nombre = btrim(regexp_replace(e.nombre, '\s+', ' ', 'g'))
  );

UPDATE cliente c
SET nombre = btrim(regexp_replace(c.nombre, '\s+', ' ', 'g'))
WHERE c.nombre <> btrim(regexp_replace(c.nombre, '\s+', ' ', 'g'))
  AND NOT EXISTS (
      SELECT 1 FROM cliente o
      WHERE o.id <> c.id AND o.nombre = btrim(regexp_replace(c.nombre, '\s+', ' ', 'g'))
  );

UPDATE agencia a
SET nombre = btrim(regexp_replace(a.nombre, '\s+', ' ', 'g'))
WHERE a.nombre <> btrim(regexp_replace(a.nombre, '\s+', ' ', 'g'))
  AND NOT EXISTS (
      SELECT 1 FROM agencia o
      WHERE o.id <> a.id AND o.nombre = btrim(regexp_replace(a.nombre, '\s+', ' ', 'g'))
  );
