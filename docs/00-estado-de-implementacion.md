# Estado de implementación del plan (23/09/2026)

> Este archivo resume qué del [plan de desarrollo](02-plan-de-desarrollo.md) ya está
> programado y qué falta. La documentación de arquitectura de
> [`01-documentacion-actual.md`](01-documentacion-actual.md) describe **la versión anterior**
> del código (útil como referencia de "de dónde veníamos"); el estado real hoy es este archivo
> más el [`README.md`](../README.md) de la raíz del proyecto.

## Hecho

| Fase | Qué se hizo |
|---|---|
| **Fase 0** | `.gitattributes` (line endings LF), notebooks de la cátedra movidos a `material-catedra/`, `test_pipeline.py` borrado (duplicaba `agent.py`), `test_stream.py` movido a `scripts/test_stream_agent.py` |
| **Fase 1 (D1)** | `config.py`, `agent.py` y `app.py` usan exclusivamente Google Gemini. No queda ninguna referencia a OpenAI ni al modo `AUTO`. El fallback ante 429/503 usa `.with_fallbacks(...)` de LangChain con `GEMINI_FALLBACK_MODEL`, en vez de detectar códigos de error a mano |
| **Fase 2 (D2)** | `get_embeddings()` usa `GoogleGenerativeAIEmbeddings` exclusivamente. Se borró `LocalHashEmbeddings`/`HashingVectorizer`. Sin `GOOGLE_API_KEY`, `get_llm()`/`get_embeddings()` lanzan `ConfigError` y la app no arranca (no hay modo degradado). La colección de Chroma se nombra incluyendo el modelo de embeddings, para no mezclar vectores de distinta dimensión si se cambia de modelo |
| **Fase 3 (D3)** | Se borraron `parse_ddl_schema`/`parse_json_schema` y el uploader de esquemas de la UI. `introspect_database()` siempre lee de `DATABASE_URL` (con `DB_SCHEMA` opcional). Se agregó `schema_fingerprint()` para reindexar el RAG solo cuando el esquema cambió. El diccionario de sinónimos hardcodeado se reemplazó por los `COMMENT ON TABLE/COLUMN` de la propia base. `seed_enterprise.py` se movió a `scripts/` y solo se ejecuta por consola (`scripts/seed_demo.py`), con confirmación explícita antes de tumbar el esquema. Se borraron `seed_data.py` y `sql/schema_seed.sql` (quedó un solo modelo de demo, el de 15 tablas). El botón "Tumbar y Recrear Base" y el de "Aplicar SQL" ya no existen en la app |
| **Fase 4 (P1)** | El modo Agente usa `create_react_agent` de LangGraph de verdad (antes se armaba y no se usaba). Herramientas: `list_tables`, `describe_table`, `retrieve_schema`, `run_select`, `run_write`. La auto-corrección sale de que `run_select` devuelve el error como texto y el agente decide cómo corregirlo, sin un prompt de "fix" aparte. Se borró `execute_copilot_step_by_step` |
| **Fase 5 (P3, P4, parte de P5)** | `sql_guard.py` ya no tiene alternativa por regex (sqlglot es obligatorio). Se corrigió el falso bloqueo de `UNION`/`INTERSECT`/`EXCEPT`/`WITH`. `INSERT` pasó de `FORBIDDEN` a `WRITE` (queda en HITL, como `UPDATE`/`DELETE`). Todos los bloqueos de las herramientas del agente quedan auditados (antes solo se auditaban desde `run_select`/`run_write`, que el pipeline viejo no usaba). Auditoría y cola HITL persistidas en `data/audit.sqlite` (`audit_store.py`), separadas por `thread_id` de sesión — ya no son diccionarios globales compartidos. `get_readonly_engine()` usa `DATABASE_URL_READONLY` si está configurada |
| **Fase 6** | `tests/test_sql_guard.py`, `tests/test_config.py`, `tests/test_introspection.py`. Los 33 casos corren sin red ni credenciales (`pytest`) |
| **Fase 7** | `README.md` reescrito con instalación, `.env` mínimo y decisiones de diseño actualizadas. `documentacion general del proyecto.md` se reemplazó por un puntero a esta documentación (el archivo original tenía afirmaciones que ya no coincidían con el código). `requirements.txt` y `.env.example` actualizados |

## Extra (no estaba en el plan original)

- `start_app.bat` y `seed_demo.bat`: automatizan en Windows la creacion del entorno virtual, la instalacion de dependencias, la creacion de `.env` desde `.env.example` y el arranque de la app / el sembrado de la base de demo. El README los documenta como "Opcion rapida".

## Pendiente

| # | Qué falta | Nota |
|---|---|---|
| P2 (parcial) | El explorador de tablas de la app sigue haciendo `SELECT * ... LIMIT 10` directo con el motor principal, no con el de solo lectura | Menor; se puede mover a `get_readonly_engine()` |
| P5 (parcial) | `DATABASE_URL_READONLY` y `DB_STATEMENT_TIMEOUT_MS` están soportados en `config.py`, pero no hay nada que verifique en el arranque que el usuario de solo lectura realmente tiene permisos restringidos | Es responsabilidad de quien configure la base, no del código |
| Sección "Dificultades encontradas" en la documentación de la defensa | No se escribió todavía como sección aparte (el README tiene las decisiones de diseño, pero no en formato "problema → solución" pensado para la defensa oral) | Fase 7, pendiente |
| **Fase 8: notebook de entrega y presentación** | No se tocó a propósito (así se pidió). `notebooks/demo.ipynb` sigue siendo el de la versión anterior del proyecto | Se hace al final, sobre la app ya cerrada |
| Verificación end-to-end contra la API real de Gemini | Se probó todo el pipeline de guardrails/HITL/auditoría con SQLite y sin LLM (funciona). Falta correr `scripts/test_stream_agent.py` con una `GOOGLE_API_KEY` real para confirmar que el agente arma buen SQL end-to-end | Necesita una clave de API real, no disponible en este entorno |
| DBML/SVG con Node.js | No se pudo probar `render_dbml_to_svg()` en este entorno (requiere Node.js + `@softwaretechnik/dbml-renderer` instalados) | Probarlo antes de la demo |

## Cómo seguir

1. Configurar un `.env` real (`DATABASE_URL` + `GOOGLE_API_KEY`) y correr `pytest` + `streamlit run db_copilot/app.py` para validar el flujo completo con la API real.
2. Sembrar la base de demo con `python scripts/seed_demo.py` si hace falta.
3. Escribir la sección de dificultades encontradas (hay material en el README, sección "Decisiones de diseño").
4. Recién ahí, Fase 8: rehacer `notebooks/demo.ipynb` y armar la presentación.
