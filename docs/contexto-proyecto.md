# Contexto del proyecto: historico de facturacion a clientes (Radio LV12)

## Que se quiere lograr
Maximiliano Gonzalez (Maxi), gerente de Radio LV12, necesita ver mes a mes cuanto factura cada cliente y agencia, como evoluciona contra el año anterior y que clientes caen o dejan de facturar. Hoy se hace con Excel a mano. Este proyecto lo pasa a una base propia con historial. El segundo proyecto (proveedores) va en otro repo mas adelante. La ocupacion de tandas queda fuera por ahora.

## Principios (guia de Vigo, CEO)
- Base propia con historial. Todo se ve en pantalla.
- El Excel es solo puerta de entrada: se importa, se valida y se guarda. No se trabaja en el.
- Escala por datos, UX simple.
- Se prueba en el entorno -dev. A produccion solo cuando el responsable (Maxi) valida.
- Entregables para gerencia: resumen, semaforo y tablas "Se automatiza / Queda manual".
- Primero se propone el esquema y Leti lo revisa. Las migraciones aplicadas no se editan.

## Stack
Python, Streamlit, psycopg3, pandas, openpyxl. PostgreSQL en Render. Migraciones SQL numeradas en `sql/migrations`, aplicadas con `scripts/migrate.py`.

## Entornos
Testing: repo y servicio `lv12-historico-clientes-dev`, base `lv12-historico-clientes-dev-db`. Produccion: `lv12-historico-clientes` y `lv12-historico-clientes-db`.

## Fuente de datos: Resumen de Publicidades 2026 (.xls, en `data/`, no se sube a git)
- Hojas mensuales "Enero 2026" a "Diciembre 2026". Enero a septiembre tienen datos; octubre a diciembre estan vacias.
- Dentro de cada mes hay bloques. Cada bloque tiene una fila de encabezado donde la columna B dice "Cliente" y termina en una fila "Totales" (se ignora).
  - "TELAM Facturado-Canje": vacio hasta ahora.
  - "AGENCIAS": columnas Cliente, Periodo, OP Agencia, Emisora, Neto, Total Iva. El nombre de la agencia esta en la columna A. En mayo y junio hay una columna extra "Factura Nº".
  - "Local Facturado" y "Local Sin Facturar": la columna de OP se llama Vendedor.
  - "COPRODUCCIONES": formato por confirmar.
  - "Canjes Facturados" (OP Agencia) y "Canjes sin Facturar" (Vendedor).
- Pestaña "Resumen": titulo dice "RESUMEN DE VENTAS 2025" pero los numeros coinciden con 2026. Se usa solo como control de totales. Por confirmar con Maxi.
- Perfil leido: 676 lineas. Agencias 212 (neto 33,92 M), Local Facturado 383 (85,91 M), Local Sin Facturar 54 (5,32 M), Canjes Facturados 11, Canjes sin Facturar 16.
- Neto mensual (millones): ene 11,90; feb 11,42; mar 11,41; abr 12,62; may 13,76; jun 16,52; jul 17,19; ago 16,05; sep 16,73.

## Reglas del importador
- Idempotente: el mismo archivo (por hash) no se carga dos veces.
- Ignora filas de Totales y bloques vacios.
- Rechaza filas sin neto o sin cliente, guardando hoja, fila y motivo en `fila_rechazada`.
- Los nombres de cliente y agencia se normalizan (minusculas, sin tildes, espacios simples) y se buscan en las tablas de alias. Si no existen, van a `nombre_pendiente` y se asignan desde pantalla. Mientras tanto no cuentan en los totales.
- Al terminar compara el neto por mes y tipo contra el Excel y muestra la diferencia.
- Periodo, emisora y OP vienen con formatos variables y pueden faltar: guardar el texto original y no inventar valores.

## Pendientes de confirmar con Maxi
1. Como se reconoce la pauta publica (hay municipios dentro de Local Facturado).
2. Si la pestaña Resumen es 2026.
3. Formato de la hoja de Coproducciones.
4. Quienes seran los usuarios: Maxi y un par de personas mas que operan. Los usuarios se crean desde Toolbox.
5. Como se integra con Ratio.

## Pantallas previstas
Tablero mensual, matriz cliente x mes, ficha de cliente, alertas, importar. Hay una maqueta de referencia.

## Fuera de esta etapa
Cobranzas (migracion 002), tarifas con vigencia, proveedores, Ratio.
