-- 005_pauta_publica.sql
-- Marca la pauta publica: cliente.tipo = 'publica' para las cinco Municipalidades (Famailla,
-- Trancas, BRS, Lules, Tafi del Valle), el Ente de Turismo, la Caja Popular de Ahorro y SAT.
-- Se buscan por nombre normalizado (minusculas, sin tildes, espacios simples) y tambien a
-- traves de cliente_alias, porque el nombre puede venir en mayusculas o con variantes
-- (por ejemplo "MUNICIPALIDAD LULES (Expo Lules)": por eso el patron de Lules termina en %).
-- Asispre NO se marca: queda 'privado' hasta que el gerente confirme.
-- Es repetible: solo toca a los que todavia no son 'publica'.

WITH publicos(patron) AS (VALUES
    ('municipalidad famailla'),
    ('municipalidad de trancas'),
    ('municipalidad brs'),
    ('municipalidad lules%'),
    ('municipalidad tafi del valle'),
    ('ente de turismo'),
    ('caja popular de ahorro'),
    ('sat')
)
UPDATE cliente c
SET tipo = 'publica'
WHERE c.tipo <> 'publica'
  AND (
      lower(btrim(regexp_replace(
          translate(c.nombre, 'áéíóúÁÉÍÓÚñÑüÜ', 'aeiouAEIOUnNuU'), '\s+', ' ', 'g')))
          LIKE ANY (SELECT patron FROM publicos)
      OR EXISTS (
          SELECT 1 FROM cliente_alias a
          WHERE a.cliente_id = c.id
            AND a.alias_normalizado LIKE ANY (SELECT patron FROM publicos)
      )
  );
