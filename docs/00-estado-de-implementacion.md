# DB Copilot: estado de implementación

> Este archivo resume, a alto nivel, qué está hecho y qué falta. El detalle técnico módulo por módulo
> está en [`01-documentacion-actual.md`](01-documentacion-actual.md) (incluida la sección de
> dificultades encontradas), y la lista completa de pendientes con próximos pasos concretos está en
> [`03-proximos-pasos.md`](03-proximos-pasos.md).

## Hecho

- **Configuración de LLM/embeddings genérica**: `LLM_PROVIDER` (`OPENAI` o `GEMINI`) elige el proveedor
  en `config.py`; solo hace falta la clave del que se use. Sin alguna variable obligatoria, la app no
  arranca (error claro, sin modo degradado).
- **Esquema siempre en vivo**: se lee por introspección de `DATABASE_URL` (SQLAlchemy), sin carga
  manual de `.sql`/`.json`. El contexto de negocio para el RAG sale de `COMMENT ON TABLE/COLUMN` de la
  propia base.
- **Agente real de LangGraph** (`create_react_agent`) con herramientas `list_tables`, `describe_table`,
  `retrieve_schema`, `run_select`, `run_write`. Auto-corrección de SQL sin prompt aparte: el agente lee
  el error que le devuelve la herramienta y reintenta.
- **Guardrails con `sqlglot`** (AST, sin regex): `UNION`/`INTERSECT`/`EXCEPT`/`WITH` se tratan como
  lectura; `INSERT`/`UPDATE`/`DELETE` quedan en HITL; `DROP`/`ALTER`/`CREATE`/`TRUNCATE` bloqueados sin
  excepción.
- **HITL y auditoría persistentes** en SQLite (`db_copilot/audit_store.py`), separados por sesión.
- **Tests** (`tests/`): guardrails, config, introspección y herramientas del agente — 52 casos sin red
  ni credenciales.
- **Base de demo reproducible en Docker**: `docker-compose.yml` precarga un Postgres con datos de
  e-commerce generados con Faker (`scripts/generate_demo_sql.py`, seed fijo), verificable con
  `scripts/verify_demo_db.py`. Quien tenga su propia base solo configura `DATABASE_URL` y no necesita
  este contenedor.
- **Puesta en marcha en Windows**: `start_app.bat` automatiza venv, dependencias (con el fix de
  `uvloop`), `.env`, Docker y la dependencia de Node del diagrama ER.
- **Probado en vivo**: Postgres real (vía Docker) + LLM real respondiendo preguntas de esquema
  correctamente.

## Pendiente

Ver el detalle completo, con acciones concretas, en
[`03-proximos-pasos.md`](03-proximos-pasos.md). En resumen:

1. Probar en vivo el modo Agente con consultas SQL reales y el flujo completo de aprobación (HITL).
2. Fase 8: rehacer `notebooks/demo.ipynb` para la entrega.
3. Preparar la presentación oral.
4. Confirmar que todos los commits estén en `origin/main` y que el equipo haga `git pull`.
5. Detalles menores: explorador de tablas usando el motor de solo lectura si está configurado.
