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
  - "AGENCIAS": columnas Cliente, Periodo, OP Agencia, Emisora, Neto, Total Iva. El nombre de la agencia esta en la columna A y viene repetido en todas las filas (en este archivo no hace falta arrastrarlo hacia abajo; el importador lo hace igual por si algun dia falta). En mayo y junio hay una columna extra "Factura Nº", pero esta vacia: `factura_nro` queda siempre vacio con este archivo.
  - "Local Facturado" y "Local Sin Facturar": la columna de OP se llama Vendedor.
  - "COPRODUCCIONES": el cliente esta en la columna A y la B esta vacia; Vendedor tambien vacio. No tiene agencia (`agencia_id` nulo).
  - "Canjes Facturados" (OP Agencia) y "Canjes sin Facturar" (Vendedor).
  - La fila "Totales" tiene el texto en la columna E y el importe en la F. La fila 1 de cada hoja dice "Mes: X  Año: 2026" y el importador la valida contra el nombre de la hoja.
  - Octubre a diciembre tienen la plantilla armada (encabezados y Totales en 0) pero ninguna fila de datos.
- Pestaña "Resumen": titulo dice "RESUMEN DE VENTAS 2025" pero los numeros coinciden con los Totales de las hojas 2026 (se comparo mes por mes y tipo por tipo), asi que es 2026; sigue conviniendo avisarle a Maxi del titulo. Unica excepcion: en julio la pestaña dice Local sin facturar 942.187,50 (la hoja Julio, 906.750,00) y Canjes facturados 259.512,50 (la hoja, 238.250,00): 56.700 de diferencia entre ambas. La conciliacion usa los Totales de las hojas mensuales. Se usa solo como control de totales.
- Perfil leido: 735 lineas, de las cuales 59 son de Coproducciones. Agencias 212 (neto 33,92 M), Local Facturado 383 (85,91 M), Local Sin Facturar 54 (5,32 M), Coproducciones 59 (7,37 M), Canjes Facturados 11, Canjes sin Facturar 16. El perfil anterior (676 lineas) no contaba Coproducciones.
- Neto mensual sin Coproducciones (millones): ene 11,90; feb 11,42; mar 11,41; abr 12,62; may 13,76; jun 16,52; jul 17,19; ago 16,05; sep 16,73. La pestaña Resumen incluye Coproducciones (ene 12,10).
- Diferencia de abril: Local Facturado suma 7.041.651,76 en las filas y el "Totales" del Excel dice 6.815.901,76 (tambien la pestaña Resumen). Son 225.750, exactamente la fila 44 (Banco Macro), la primera del bloque: parece quedar fuera de la formula del Excel. Se carga igual y la tabla de control muestra la diferencia. Consultar a Maxi.
- Periodo viene en formatos variables y se guarda tal cual en `periodo_texto`: nombre de mes en mayusculas ("ENERO"), rangos de fechas con conectores mezclados ("26/01 al 25/02", "04/06 A 13/07", "17/06 a 15/07"), rangos con errores de tipeo ("01/07 al 3107", "14/05 al 8/05") y textos de varios meses ("JULIO 25 a JULIO 26", "FEB A JUNIO", "FEB. A ABR."). El anio y el mes salen de la hoja, no del texto.
- Nombres de agencia: 32 escrituras distintas para unas 14 agencias (ej. "Arena SA", "Arena Argentina", "Arena Argentina SA", "Arena Arg. SA"; espacios al final; mayusculas distintas). Con la normalizacion quedan 26 agencias creadas, y las parecidas (similitud >= 0,9) van a `sugerencia_fusion` para fusionar a mano.
- Emisoras: 24 escrituras en el archivo (ej. "4 RADIOS"/"4 Radios", "CONT"/"CONT."/"CONTINENTAL", "LA 750"/"LA750", un "750" numerico). Se normalizan mayusculas, espacios y espacios alrededor de "/" (quedan 20); CONT / CONT. / CONTINENTAL y las combinaciones de varias radios no se unifican.
- Vendedor con codigos de OP: 20 filas de Local Facturado (todas de Banco Macro, junio a septiembre) traen en la columna Vendedor codigos tipo "772813/1". Se guardan en `vendedor` tal cual; el importador los lista al final para consultar a Maxi.

## Reglas del importador
- Idempotente: el mismo archivo (por hash) no se carga dos veces.
- Ignora filas de Totales y bloques vacios.
- Rechaza filas sin neto o sin cliente, guardando hoja, fila y motivo en `fila_rechazada`.
- Los nombres de cliente y agencia se normalizan (minusculas, sin tildes, espacios simples) y se buscan en las tablas de alias. Si no existen, se crean con el nombre tal como viene y se registra su alias; las lineas se cargan siempre. Si el nombre nuevo se parece (similitud >= 0,9, difflib) a uno existente, se registra en `sugerencia_fusion` (migracion 002, reemplaza a `nombre_pendiente`) para fusionarlo desde pantalla; la sugerencia no afecta las lineas ni los totales.
- Al terminar compara el neto por mes y tipo contra el Excel y muestra la diferencia.
- Periodo, emisora y OP vienen con formatos variables y pueden faltar: guardar el texto original y no inventar valores.

## Pendientes de confirmar con Maxi
1. Como se reconoce la pauta publica (hay municipios dentro de Local Facturado).
2. Avisarle del titulo "2025" de la pestaña Resumen (los numeros son 2026) y preguntar por la fila de Banco Macro de abril que el Totales no suma (225.750), por los codigos de OP en la columna Vendedor y por julio, donde la pestaña Resumen difiere de la hoja Julio en 56.700 (Local sin facturar y Canjes facturados).
3. (Resuelto) Formato de la hoja de Coproducciones: cliente en la columna A.
4. Quienes seran los usuarios: Maxi y un par de personas mas que operan. Los usuarios se crean desde Toolbox.
5. Como se integra con Ratio.

## Pantallas previstas
Tablero mensual, matriz cliente x mes, ficha de cliente, alertas, importar. Hay una maqueta de referencia.

## Fuera de esta etapa
Cobranzas (migracion 002), tarifas con vigencia, proveedores, Ratio.
