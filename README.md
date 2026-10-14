# LV12 - Historico y evolucion de facturacion a clientes

Sistema para Radio LV12 que guarda en una base propia el historico de facturacion por
cliente, para ver como salio cada mes, como viene el ano y donde actuar (agencias que bajan
su pauta, marcas que discontinuaron, tarifas sin actualizar). Reemplaza el armado manual en
varios Excel (Resumen de Publicidades y Cobranzas).

Stack: Python + Streamlit, PostgreSQL en Render.

## Ambientes

| Ambiente | Repositorio | Servicio Render | Base |
|---|---|---|---|
| Testing | `lv12-historico-clientes-dev` | `lv12-historico-clientes-dev` | `lv12-historico-clientes-dev-db` |
| Produccion | `lv12-historico-clientes` | `lv12-historico-clientes` | `lv12-historico-clientes-db` |

El trabajo diario es en Testing. Produccion solo recibe codigo ya probado y validado por el
responsable (Federico Vigo).

## Setup local

1. `python -m venv .venv` y activarlo.
2. `pip install -r requirements.txt`
3. `copy .env.example .env` y completar `DATABASE_URL` con la External Database URL de la
   base de testing en Render.
4. `python scripts/migrate.py` aplica las migraciones pendientes.
5. `streamlit run app.py`

Los Excel reales de la radio van en `data/` (no se versiona en git).

## Render (Start Command)

`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`

Variable de entorno requerida: `DATABASE_URL` (la Internal Database URL de la base del mismo
ambiente).

## Estructura

- `app.py`: pantalla principal.
- `src/db.py`: acceso a la base.
- `sql/migrations/`: cambios de estructura, numerados. Una migracion aplicada no se edita.
- `scripts/migrate.py`: aplica las migraciones pendientes.
- `data/`: archivos del cliente (ignorado por git).

## Estado actual

Estructura base. Falta definir el modelo de datos (en revision) antes de escribir la primera
migracion.

## Principios (guia de diseno del Holding)

Base propia con esquema solido, historial de lo que se carga y calcula, todo el flujo en
pantalla (Excel solo como puerta de entrada o boton de exportar), sumar un caso nuevo es
cargar un dato y no codigo, uso simple para personas no tecnicas, proceso completo. Reglas de
negocio comentadas en el codigo con su motivo.

## Decisiones abiertas

- Acceso a los datos de Ratio (base, API o solo exportacion).
- Como distinguir pauta publica (municipio, legislatura) en los archivos de origen.
- Si la pestana "Resumen" del Excel de publicidades (titulo 2025) es en realidad de 2026.
- Quienes usan el sistema y con que permisos (ver, operar, administrar). Acceso via Toolbox.
