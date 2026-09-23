# DB Copilot: plan de desarrollo

> **Actualizacion (23/09/2026):** las fases 0 a 7 de este plan ya estan programadas. El detalle de que se hizo y que quedo pendiente esta en [`00-estado-de-implementacion.md`](00-estado-de-implementacion.md). Este archivo se deja tal cual quedo redactado como plan original.


> Parte del estado descrito en [`01-documentacion-actual.md`](01-documentacion-actual.md).
> **Alcance:** dejar bien la **app**. El notebook de entrega y la presentación se hacen al final (fase 8), a partir de la app terminada.
> **Fecha límite:** defensa el **30/09** o el **14/10** (tarde/noche), o el **01/10** o el **08/10** (mañana). Conviene tener la app cerrada unos días antes de la primera fecha.

---

## 1. Decisiones tomadas

| # | Decisión | Consecuencia |
|---|---|---|
| D1 | **Solo Gemini**, se deja de usar la API de OpenAI | Se elimina `langchain-openai`, el modo `AUTO` y toda rama `OPENAI` |
| D2 | **Embeddings de Gemini y nada de HashingVectorizer** | Si no hay `GOOGLE_API_KEY` válida, la app **falla al arrancar** con un error claro. No hay fallback local |
| D3 | **El esquema se lee de la base del `.env`** | Se elimina la carga manual de esquemas (`.sql`/`.json`). `DATABASE_URL` pasa a ser obligatoria |
| D4 | El notebook se rehace al final | No se toca `notebooks/demo.ipynb` hasta la fase 8 |

## 2. Decisiones propuestas (confirmar antes de programar)

| # | Propuesta | Por qué |
|---|---|---|
| P1 | Usar el **agente de LangGraph de verdad** (`create_react_agent`) en el modo Agente, en lugar del pipeline fijo | La consigna y la documentación hablan de agente. Hoy el agente está armado y no se usa. La auto-corrección sale sola: el agente ve el error que le devuelve la herramienta y reintenta |
| P2 | Sacar de la UI los botones que destruyen o modifican el esquema ("Tumbar y recrear", "Aplicar SQL") y pasar el sembrado a un script de consola (`scripts/seed_demo.py`) | Con D3, la base del `.env` puede ser real. Un botón que hace `DROP SCHEMA CASCADE` no puede estar en la app |
| P3 | Permitir `UNION`/`INTERSECT`/`EXCEPT` como lectura y seguir bloqueando `INSERT` (o pasarlo por HITL, a elegir) | Hoy se bloquean lecturas legítimas |
| P4 | Guardar la auditoría y la cola HITL en un archivo local (SQLite o JSONL en `data/`), no solo en memoria | Que sobrevivan a un reinicio de Streamlit durante la demo |
| P5 | Usar un **usuario de base de solo lectura** para los `SELECT` (opcional `DATABASE_URL_READONLY`) y `statement_timeout` en Postgres | Defensa en profundidad además de sqlglot. Suma en la defensa |

---

## 3. Fases

Cada tarea indica los archivos que toca y cuándo se considera terminada ("Listo cuando").

### Fase 0: preparación del repo (≈ 0,5 h)
- [ ] Crear la rama `refactor/gemini-only`.
- [ ] Agregar `.gitattributes` (`* text=auto eol=lf`, `*.bat eol=crlf`) y normalizar finales de línea, para terminar con los 23 archivos "modificados" sin cambios.
- [ ] Mover los notebooks de la cátedra a `material-catedra/` o sacarlos del repo.
- [ ] Borrar `test_pipeline.py` (duplica `agent.py`). Mover `test_stream.py` a `scripts/` como prueba manual.
- **Listo cuando:** `git status` está limpio y la raíz solo tiene archivos del proyecto.

### Fase 1: solo Gemini para el LLM (≈ 1,5 h)
- [ ] `config.py`: reescribir `get_llm()` para que use solo `ChatGoogleGenerativeAI`.
  - Leer `GOOGLE_API_KEY`, `GEMINI_MODEL` y `GEMINI_FALLBACK_MODEL` (opcional).
  - Si falta la clave → `raise ConfigError("Falta GOOGLE_API_KEY en .env")`.
  - Borrar la "sanitización" de prefijos de claves y la detección `AUTO`.
- [ ] Revisar cómo se pide el "thinking" en la versión instalada de `langchain-google-genai`: hoy se pasa `thinking_config={...}` dentro de un `try` que nunca falla al construir el objeto. Usar los parámetros que documente la librería (por ejemplo `include_thoughts` / `thinking_budget`) y probarlo.
- [ ] `agent.py`:
  - el fallback por 429/503 usa `GEMINI_FALLBACK_MODEL` del `.env` (sin nombres de modelo escritos a mano);
  - sacar el `provider_name` que distingue entre OpenAI y Gemini.
- [ ] `app.py`: la barra lateral muestra solo el modelo de Gemini (leído de `config`, no con otro defecto propio).
- [ ] `requirements.txt` y `.env.example`: sacar todo lo de OpenAI.
- **Listo cuando:** `grep -ri openai db_copilot/` no devuelve nada, y sin `GOOGLE_API_KEY` la app muestra un error claro y no arranca.

### Fase 2: embeddings de Gemini, sin fallback (≈ 1,5 h)
- [ ] `config.py`: `get_embeddings()` devuelve `GoogleGenerativeAIEmbeddings(model=GEMINI_EMBEDDING_MODEL)`, por ejemplo `gemini-embedding-001`, configurable. Borrar `LocalHashEmbeddings`.
- [ ] Usar el tipo de tarea correcto: documento al indexar, consulta al buscar (si la versión de la librería lo permite).
- [ ] Comprobar la API al arrancar: embeber un texto corto. Si falla (clave inválida, sin cuota, sin red), **cortar con un mensaje claro**. No seguir en modo degradado.
- [ ] `rag.py`:
  - el nombre de la colección de Chroma incluye el modelo de embeddings, porque cambiar de modelo cambia la dimensión de los vectores y Chroma falla si mezcla dimensiones;
  - borrar la `data/chroma_db` vieja, creada con vectores de 1024 dimensiones del HashingVectorizer.
- [ ] Sacar `scikit-learn` de las dependencias si ya no se usa.
- **Listo cuando:** la búsqueda "¿dónde están los pedidos de los clientes?" trae `orders` y `customers` aunque la pregunta no nombre las tablas en inglés. Esa es la prueba de que los embeddings son semánticos.

### Fase 3: el esquema sale siempre de la base del `.env` (≈ 3 h)
- [ ] `config.py`: `DATABASE_URL` obligatoria (si falta, error claro; se borra el valor por defecto de Postgres). Nueva variable opcional `DB_SCHEMA` (por defecto `public`) para introspectar solo ese schema.
- [ ] `schema_introspection.py`:
  - [ ] `introspect_database(engine, schema)`: pasar `schema=` al inspector y leer **los comentarios** de tablas y columnas (`get_table_comment`, `col["comment"]`). Esa pasa a ser la fuente de contexto de negocio.
  - [ ] Cantidad de filas: en Postgres usar la estimación `pg_class.reltuples`, no `COUNT(*)`, que es lento en tablas grandes.
  - [ ] Borrar `synonyms_map`, escrito a mano para la base de demo. **Opcional:** generar con Gemini una descripción corta y sinónimos en español por tabla, una vez por esquema, y guardarlos en caché en `data/` para no gastar llamadas en cada arranque.
  - [ ] Borrar `parse_ddl_schema` y `parse_json_schema`.
  - [ ] Agregar `schema_fingerprint(meta)`, un hash de tablas, columnas y FK, para saber si hace falta reindexar.
- [ ] `rag.py` / `app.py`:
  - al arrancar, introspección → fingerprint → reindexar solo si el esquema cambió;
  - dejar un botón **"🔄 Resincronizar esquema"** que fuerce el reindexado.
- [ ] `agent.py`: sacar del prompt de corrección la pista `c.name → first_name/last_name`, que es propia de la base de demo.
- [ ] `app.py`:
  - borrar el uploader de esquema y el selector entre el esquema de 15 y el de 4 tablas;
  - la pestaña "Carga y gestión de esquema" pasa a ser **"Esquema"**, de solo lectura: tablas, columnas, FK y DDL reconstruido;
  - siguen el diagrama DBML y el explorador de tablas.
- [ ] Datos de demo (P2):
  - `seed_enterprise.py` se mueve a `scripts/seed_demo.py` y se usa por consola (`python scripts/seed_demo.py --url ... --orders 1500`);
  - antes de hacer `DROP SCHEMA`, pide confirmación escrita;
  - `seed_data.py` y `sql/schema_seed.sql` (el modelo de 4 tablas) se borran, así queda un solo modelo de demo;
  - opcional: agregar `COMMENT ON TABLE/COLUMN` al DDL de demo, para que la introspección tenga contexto de negocio real.
- **Listo cuando:** cambiando solo `DATABASE_URL` a otra base, la app arranca, indexa ese esquema y contesta sobre él. No hace falta pegar ni subir nada.

### Fase 4: modo Agente con LangGraph de verdad (P1, ≈ 4 h)
- [ ] Herramientas:
  - `list_tables()`;
  - `describe_table(name)`: columnas y FK exactas, desde la introspección;
  - `retrieve_schema(query)`: búsqueda semántica;
  - `run_select(sql)`;
  - `run_write(sql)`.

  Las herramientas **devuelven el error como texto** (no lanzan excepciones), así el agente puede corregirse solo.
- [ ] `DBCopilot.ask(mode="agent")` usa `agent_graph.stream(..., stream_mode="updates")`:
  - cada nodo o llamada a herramienta se convierte en un paso de la timeline, así la UI de observabilidad no cambia;
  - `recursion_limit` (por ejemplo 8) evita que el agente entre en un bucle.
- [ ] Memoria de conversación por sesión (`thread_id` = id de sesión de Streamlit) para preguntas de seguimiento ("¿y de esos, cuáles son de Rosario?").
- [ ] La respuesta final la escribe el agente **después** de ver el resumen del resultado, no antes.
- [ ] Borrar `execute_copilot_step_by_step`. **Alternativa:** si P1 se rechaza, conservarlo pero presentarlo como "pipeline RAG con herramientas".
- **Listo cuando:** en la timeline se ve que el agente decide qué herramientas usar. Un caso de prueba con una columna mal escrita se corrige solo, sin código especial de auto-corrección.

### Fase 5: guardrails y seguridad (≈ 2 h)
- [ ] `sql_guard.py`:
  - hacer `sqlglot` **obligatorio** y borrar la alternativa por regex;
  - aceptar `exp.Union`, `exp.Intersect`, `exp.Except` y `WITH` como `SELECT`, e inyectar el `LIMIT` en la consulta externa;
  - decidir qué pasa con `INSERT` (P3).
- [ ] Auditar **todos** los bloqueos, también los del agente.
- [ ] P4: guardar la auditoría y la cola HITL en `data/audit.sqlite`.
- [ ] P5: engine de solo lectura para `run_select` si existe `DATABASE_URL_READONLY`, y `SET statement_timeout` en Postgres.
- [ ] Mover el estado global (`_context_store`, etc.) a `st.session_state` o a un objeto por sesión, para que dos pestañas del navegador no se pisen.
- **Listo cuando:** pasan los tests de la fase 6.

### Fase 6: tests (≈ 2 h)
- [ ] `tests/test_sql_guard.py`, con casos en tabla:
  - `SELECT` sin/con `LIMIT`, `WITH`, `UNION`;
  - `UPDATE` con/sin `WHERE`, `DELETE`;
  - varias sentencias, `DROP`, `ALTER`, `TRUNCATE`, `INSERT`;
  - comentarios `/* */`, un string con `'DROP'` adentro (no tiene que bloquearse).
- [ ] `tests/test_introspection.py`: base SQLite temporal con 3 tablas y FK → metadatos y documentos esperados.
- [ ] `tests/test_config.py`: sin `GOOGLE_API_KEY` y sin `DATABASE_URL`, `get_llm`/`get_embeddings`/`get_engine` lanzan el error esperado.
- [ ] `tests/test_e2e_gemini.py` (marcado `@pytest.mark.gemini`, se corre a mano): 5 preguntas de referencia contra la base de demo, verificando el tipo de respuesta y que el SQL sea válido.
- **Listo cuando:** `pytest -m "not gemini"` pasa sin red y sin clave.

### Fase 7: documentación (≈ 2 h)
- [ ] Reescribir `README.md`: instalación, `.env` mínimo (`DATABASE_URL`, `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`), cómo sembrar la base de demo y cómo correr la app.
- [ ] Actualizar `documentacion general del proyecto.md`, o reemplazarlo por `docs/03-arquitectura.md`, para que coincida con el código: agente real, solo Gemini, esquema desde la base. Corregir los links `file:///c:/proyectos/...` por rutas relativas.
- [ ] Nueva sección **"Dificultades encontradas y cómo se resolvieron"**, que es criterio de evaluación:
  - el LLM inventaba columnas → RAG del esquema y auto-corrección;
  - límites de cuota (429) → modelo de respaldo;
  - regex frágil → AST con sqlglot;
  - miles de filas en el prompt → separar el canal de datos del de texto;
  - pipeline fijo → agente;
  - HashingVectorizer → embeddings reales;
  - esquema pegado a mano → introspección.
- [ ] `requirements.txt` completo y con versiones mínimas probadas.
- [ ] Actualizar `docs/01-documentacion-actual.md` al estado final.

### Fase 8: entrega (después de cerrar la app)
- [ ] **Notebook nuevo** `notebooks/entrega_tp2.ipynb`:
  - agrega la raíz del proyecto a `sys.path` y lee el `.env`;
  - muestra introspección → documentos → embeddings → retriever → modo Documentación → agente con sus pasos → guardrails → HITL → auditoría;
  - incluye casos de prueba con resultados;
  - se entrega **ejecutado, con las salidas guardadas**.
- [ ] Presentación: caso de negocio, arquitectura, decisiones, dificultades, resultados y demo en vivo con un plan B (capturas o video) por si falla la red.
- [ ] Repasar el **TP1** (clasificación de alumnos con redes neuronales).

---

## 4. Orden sugerido y estimación

| Día | Fases | Horas aprox. |
|---|---|---|
| 1 | 0, 1, 2 | 3,5 |
| 2 | 3 | 3 |
| 3 | 4 | 4 |
| 4 | 5, 6 | 4 |
| 5 | 7 | 2 |
| 6-7 | 8 (notebook y presentación) | 5-6 |

Las fases 1, 2 y 3 son las que se pidieron y dependen poco entre sí. La 4 depende de la 3 (herramientas `describe_table`/`list_tables`). La 6 se puede ir escribiendo junto con cada fase.

---

## 5. Variables de entorno al terminar

```env
# Obligatorias
DATABASE_URL=postgresql+psycopg2://usuario:pass@host:5432/base
GOOGLE_API_KEY=...

# Opcionales
DB_SCHEMA=public
GEMINI_MODEL=<modelo flash vigente>
GEMINI_FALLBACK_MODEL=<modelo flash-lite vigente>
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
DATABASE_URL_READONLY=postgresql+psycopg2://lector:pass@host:5432/base
```

> Los nombres de modelo de Gemini cambian seguido. Antes de fijarlos, confirmarlos en <https://ai.google.dev/gemini-api/docs/models>.

---

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Cuota gratuita de Gemini agotada durante la defensa | Modelo de respaldo, clave de reserva, demo grabada como plan B |
| Sin internet en el aula | Con D2 la app no arranca sin API, así que el plan B es el notebook ejecutado con salidas guardadas y un video |
| El agente ReAct tarda más que el pipeline (más llamadas al LLM) | `recursion_limit`, modelo flash y la timeline visible para explicarlo |
| Chroma con vectores de dimensión vieja | Colección nombrada por modelo y borrado de `data/chroma_db` en la fase 2 |
| Base real del `.env` modificada por error | P2 (sin botones destructivos), P5 (usuario de solo lectura) y HITL |
