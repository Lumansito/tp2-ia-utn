# DB Copilot: documentación técnica actual

> **Estado:** este documento describe el código **tal como está hoy** (25/09/2026), después del
> refactor de las fases 0 a 7 del [plan de desarrollo](02-plan-de-desarrollo.md) y de los ajustes que
> hizo el equipo sobre esa base (configuración genérica de `.env`, rediseño de la UI, base de demo en
> Docker). Qué falta todavía está en [`03-proximos-pasos.md`](03-proximos-pasos.md).

---

## 1. Contexto: qué pide la consigna

**TP2: Sistemas Inteligentes con RAG o Agentes** (Inteligencia Artificial, ISI, UTN).

| Tema | Qué pide |
|---|---|
| Framework | LangChain como framework principal |
| Enfoque | Un **agente** que use varias herramientas (búsqueda, APIs, bases de datos) **o** un sistema **RAG** |
| Modelo | GPT, LLaMA u otro (Gemini es válido) |
| Embeddings | Si hacen falta para representar documentos o consultas |
| Reproducibilidad | La lógica tiene que estar documentada y ser reproducible en un **notebook interactivo** |
| Entregables | 1) Notebook con el sistema, código y comentarios. 2) Presentación oral: caso de negocio, cómo se resolvió con IA, decisiones, dificultades y resultados |
| Criterios | Funcionamiento con casos de prueba, marco teórico (RAG, agentes, NLP, embeddings), creatividad, documentación técnica, **identificación de dificultades**, presentación y defensa |
| Fechas de defensa | Tarde/noche: **mié 30/09** y **mié 14/10**. Mañana: **jue 01/10** y **jue 08/10** |
| Extra | En la defensa hacen 1 o 2 preguntas sobre el **TP1** (clasificación de alumnos con redes neuronales) |

DB Copilot cubre el enfoque de **agente + RAG combinados**: RAG puro para preguntas de esquema, y un
agente ReAct de LangGraph con herramientas (incluida una de recuperación semántica) para consultas y
modificaciones de datos.

---

## 2. Qué es DB Copilot

Un asistente que permite consultar y operar sobre una base de datos relacional (PostgreSQL o SQLite)
en lenguaje natural. El caso de negocio: en las empresas, entender el modelo de datos y escribir SQL
correcto depende de pocas personas (DBAs o seniors), y eso genera cuellos de botella para el resto.

Tiene dos modos de uso:

1. **Modo Documentación (RAG):** responde preguntas sobre la **estructura** de la base (tablas,
   columnas, relaciones, índices) sin ejecutar SQL.
2. **Modo Agente SQL:** un agente decide qué herramientas usar para convertir un pedido en SQL,
   validarlo con guardrails, ejecutarlo (lecturas) o dejarlo pendiente de aprobación humana
   (escrituras), y mostrar el resultado en una tabla.

---

## 3. Stack tecnológico

| Capa | Tecnología |
|---|---|
| LLM | Gemini (`langchain-google-genai`) **o** OpenAI (`langchain-openai`), elegido por `LLM_PROVIDER` en `.env` |
| Embeddings | Del mismo proveedor elegido: `GoogleGenerativeAIEmbeddings` o `OpenAIEmbeddings` |
| Vector store | ChromaDB (`langchain-chroma`), persistido en `data/chroma_db`, con la colección nombrada según el modelo de embeddings activo |
| Orquestación | LangGraph `create_react_agent` (modo Agente, con checkpointer `InMemorySaver` por sesión) y LCEL (modo Documentación) |
| Base de datos | SQLAlchemy 2 + psycopg2 (PostgreSQL) o SQLite |
| Guardrails SQL | `sqlglot` (parser AST), sin alternativa por regex |
| Auditoría / HITL | SQLite local (`data/audit.sqlite`), separado por `thread_id` de sesión |
| UI | Streamlit |
| Datos de demo | Faker (seed fijo), precargados en un Postgres de `docker-compose.yml` |
| Diagramas | DBML generado en Python, renderizado a SVG con Node (`@softwaretechnik/dbml-renderer`) |

---

## 4. Estructura del repositorio

```
tp2-ia-utn/
├── db_copilot/
│   ├── __init__.py
│   ├── config.py                 # .env, engine SQLAlchemy, fábricas de LLM y embeddings
│   ├── schema_introspection.py   # Introspección en vivo, documentos NLP para el RAG, DBML/DDL
│   ├── rag.py                    # Chroma: indexado, retriever balanceado, respuesta modo Documentación
│   ├── sql_guard.py              # Validación y clasificación de SQL con sqlglot
│   ├── agent.py                  # Herramientas @tool, agente ReAct de LangGraph, HITL
│   ├── audit_store.py            # Auditoría y cola HITL persistidas en SQLite
│   └── app.py                    # App Streamlit (Chat, Esquema, Diagrama ER, Auditoría)
├── scripts/
│   ├── generate_demo_sql.py      # Genera docker/init/01_schema_and_seed.sql (Faker, seed fijo)
│   └── verify_demo_db.py         # Verifica que la base de demo de Docker cargó bien
├── docker/init/01_schema_and_seed.sql   # Se ejecuta solo al iniciar Postgres con el volumen vacío
├── docker-compose.yml
├── tests/                         # pytest: sql_guard, config, introspección, herramientas del agente
├── notebooks/demo.ipynb          # Pendiente de rehacer para la entrega (fase 8)
├── docs/                          # Esta documentación
├── render_dbml.js                # Node: DBML → SVG
├── package.json / package-lock.json
├── start_app.bat
├── requirements.txt
└── .env.example
```

`data/` (SQLite del audit log y Chroma) se crea sola al importar `config.py` y está en `.gitignore`.

---

## 5. Configuración actual (`.env`)

| Variable | Uso | Obligatoria |
|---|---|---|
| `DATABASE_URL` | Conexión de SQLAlchemy a la base a consultar | Sí |
| `LLM_PROVIDER` | `OPENAI` o `GEMINI` | Sí |
| `LLM_API_KEY` | Clave del proveedor elegido | Sí |
| `LLM_MODEL` | Modelo de lenguaje (ej. `gemini-3.8-flash`, `gpt-4o-mini`) | Sí |
| `EMBEDDING_MODEL` | Modelo de embeddings del mismo proveedor | Sí |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Solo si se usa el Postgres de `docker-compose.yml` | No |
| `POSTGRES_PORT` | Puerto host del Postgres de Docker (default `5432`) | No |
| `DB_SCHEMA` | Restringe la introspección a un schema puntual de Postgres | No |

Si falta cualquiera de las variables obligatorias, `config.py` lanza un `ValueError` con el nombre de
la variable faltante y la app no arranca — no hay modo degradado.

---

## 6. Cómo funciona, módulo por módulo

### 6.1 `config.py`
- Carga `.env`, crea `data/` y `data/chroma_db/`.
- `get_engine(url)`: normaliza `postgresql://` a `postgresql+psycopg2://`. En SQLite pasa
  `check_same_thread=False`.
- `get_llm(temperature=0.0)`: lee `LLM_PROVIDER`/`LLM_API_KEY`/`LLM_MODEL` y arma `ChatOpenAI` o
  `ChatGoogleGenerativeAI` (con `thinking_config={"include_thoughts": True}` para exponer el
  razonamiento del modelo en la UI). Sin alguna de las tres variables, o con un proveedor no
  reconocido, lanza `ValueError`.
- `get_embeddings()`: misma lógica que `get_llm()`, pero para `OpenAIEmbeddings` /
  `GoogleGenerativeAIEmbeddings`, usando `EMBEDDING_MODEL`.

### 6.2 `schema_introspection.py`
- `introspect_database(engine, schema=None)`: usa `sqlalchemy.inspect()` para leer tablas, columnas
  (tipo, nulabilidad, default, comentario), PK, FK e índices, más `COMMENT ON TABLE` de cada tabla. La
  cantidad de filas la estima con `pg_class.reltuples` en Postgres (no `COUNT(*)`, para no ser lento en
  bases grandes) y con `COUNT(*)` en SQLite.
- `schema_fingerprint(meta)`: hash estable de tablas/columnas/FK, para decidir si hace falta reindexar
  el RAG (evita llamar a la API de embeddings en cada arranque si el esquema no cambió).
- `generate_natural_language_docs(meta)`: arma los documentos para indexar en el RAG — 1 documento del
  motor, 1 por tabla (con su `COMMENT ON TABLE`/`COMMENT ON COLUMN` si existen), 1 por cada FK y 1 por
  cada índice.
- `generate_ddl_preview(meta)` / `generate_single_table_ddl(name, meta)`: reconstruyen un DDL
  aproximado (no necesariamente ejecutable) para mostrar en la pestaña Esquema.
- `generate_dbml(meta)` / `render_dbml_to_svg(dbml)`: arman el diagrama ER llamando a
  `node render_dbml.js` (si Node no está disponible, la UI muestra el DBML en texto sin el SVG).

### 6.3 `rag.py`
- `_collection_name()`: la colección de Chroma incluye el nombre del modelo de embeddings activo, para
  no mezclar vectores de distinta dimensión si se cambia de modelo.
- `index_schema_documents(docs)`: aplica `RecursiveCharacterTextSplitter` (700 caracteres, overlap 80),
  resetea la colección y vuelve a indexar todo.
- `retrieve_schema_context(query, k=4)`: recuperación balanceada — hasta `max(k,4)` documentos de tipo
  `tabla` y hasta `max(k-1,3)` de tipo `relacion`; si no trae nada, hace una búsqueda sin filtro.
- `answer_schema_question(query)`: **modo Documentación**. Cadena LCEL
  `ChatPromptTemplate | llm | StrOutputParser`, con la instrucción de responder solo con el contexto
  recuperado.

### 6.4 `sql_guard.py`: `validate_and_classify_sql(sql, default_limit=500, dialect)`

| Entrada | Clasificación | Qué hace |
|---|---|---|
| Vacío o con error de sintaxis | `INVALID` | Rechaza |
| Más de una sentencia encadenada | `FORBIDDEN` | Rechaza |
| `SELECT`, o `UNION`/`INTERSECT`/`EXCEPT`/`WITH` de `SELECT`s | `SELECT` | Si no tiene `LIMIT`, se lo inyecta en el AST |
| `INSERT` / `UPDATE` / `DELETE` | `WRITE` | Válido, pero **nunca se ejecuta directamente**: queda pendiente de aprobación humana. En `UPDATE`/`DELETE` sin `WHERE` agrega una advertencia |
| `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `Command`, `Grant` | `FORBIDDEN` | Rechaza sin excepción |
| Cualquier otro tipo de nodo AST no contemplado | `FORBIDDEN` | Rechaza |

`sqlglot` es una dependencia obligatoria: no hay alternativa por expresiones regulares (un guardrail
por regex es evadible con comentarios SQL o cadenas literales).

### 6.5 `audit_store.py`
Dos tablas en `data/audit.sqlite`:
- `audit_log`: cada intento de ejecución (bloqueado, ejecutado, con error), con `thread_id`, SQL,
  clasificación, filas afectadas y timestamp.
- `pending_writes`: la cola HITL — cada `INSERT`/`UPDATE`/`DELETE` propuesto por el agente, con estado
  `PENDING` → `EXECUTED`/`REJECTED`/`EXECUTION_FAILED`.

Reemplaza a los diccionarios globales en memoria de la primera versión: sobrevive a un reinicio de la
app y separa las sesiones (dos pestañas del navegador, o dos usuarios, no se pisan).

### 6.6 `agent.py`
- **Herramientas (`@tool`)**, armadas por sesión (`make_tools(thread_id)`):
  - `list_tables()`, `describe_table(table_name)`: metadatos exactos, para que el agente no invente
    nombres de columnas.
  - `retrieve_schema(query)`: llama al retriever del RAG.
  - `run_select(sql)`: guardrail → ejecuta con pandas → guarda el `DataFrame` completo en el contexto
    de la sesión y devuelve al LLM solo un resumen (filas, columnas, muestra de 2 filas). Si falla,
    devuelve el error del motor como texto para que el agente lo lea y corrija el SQL él mismo — no
    hay un prompt de "auto-corrección" aparte.
  - `run_write(sql)`: guardrail → si es válida, la encola en `audit_store` con un ID y devuelve ese ID.
    Nunca ejecuta directamente.
- `approve_pending_write(id, approve, operator)`: el único punto del código que ejecuta una escritura
  contra la base, dentro de una transacción (`engine.begin()`), y solo tras aprobación explícita.
- `DBCopilot`: arma un `create_react_agent` de LangGraph por sesión (`_graph_for(thread_id)`), con
  `InMemorySaver` como checkpointer (memoria de conversación dentro de la sesión de Streamlit).
  - `ask(question, mode="schema")`: RAG puro (`answer_schema_question`), con timeline de pasos.
  - `ask(question, mode="agent")`: `graph.stream(..., stream_mode="updates")`, registrando cada
    decisión del agente y cada resultado de herramienta como un paso de la timeline que se muestra en
    la UI ("Detalle de ejecución").

### 6.7 `app.py` (Streamlit)
- **Arranque (`initialize_system`)**: `get_engine()` → introspección → si el fingerprint del esquema
  cambió, reindexa el RAG → `get_llm()` → `DBCopilot`. Si algo falla, la barra lateral lo muestra con
  un botón de reintento.
- **Barra lateral:** información del entorno (motor, versión, host, base, proveedor, modelo) y estado
  del sistema, con botón para resincronizar el esquema a mano.
- **Banner de aprobaciones pendientes:** botones Aprobar / Rechazar por cada escritura en cola.
- **Pestañas:**
  1. **Chat:** selector Agente / Documentación, historial, SQL ejecutado, DataFrame con descarga CSV,
     detalle de ejecución (timeline) por mensaje.
  2. **Esquema:** selector de tabla, métricas (PK, columnas, filas estimadas), estructura con
     restricciones y FK, DDL de la tabla y de todo el esquema — todo de solo lectura.
  3. **Diagrama:** DBML descargable y su render SVG (si Node está disponible).
  4. **Auditoría:** el log completo de `audit_store`.

---

## 7. Flujos de punta a punta (como están hoy)

**Modo Documentación:** pregunta → retriever de Chroma (tablas + relaciones) → prompt LCEL → LLM
configurado → respuesta en texto. No toca la base.

**Modo Agente, lectura:** pregunta → el agente decide invocar `retrieve_schema` y/o `describe_table` →
genera SQL → `run_select` → sqlglot clasifica y agrega `LIMIT` si falta → pandas `read_sql` →
`DataFrame` a la UI, resumen al agente → respuesta final en lenguaje natural.

**Modo Agente, error de SQL:** `run_select` devuelve el error del motor como texto → el agente lo lee,
corrige el SQL con la ayuda de `describe_table` si hace falta, y reintenta él mismo (sin límite de
reintentos fijo más allá del `recursion_limit` del grafo).

**Modo Agente, escritura:** `INSERT`/`UPDATE`/`DELETE` → `run_write` la valida y la encola en
`audit_store` → aparece en el banner de aprobaciones → el operador aprueba o rechaza desde la UI →
si se aprueba, se ejecuta en una transacción y queda auditada con las filas afectadas.

**Bloqueo:** múltiples sentencias, DDL o cualquier SQL inválido → `FORBIDDEN`/`INVALID` → se audita
igual (a diferencia de la primera versión, todos los bloqueos quedan registrados, no solo los de
`run_select`/`run_write`).

---

## 8. Estado de los entregables

| Entregable | Estado |
|---|---|
| App funcional | ✅ Probada en vivo (Postgres real + LLM real): RAG de esquema, base de demo de Docker cargada y verificada |
| Guardrails + HITL + auditoría | ✅ Cubiertos por `tests/` sin red ni credenciales |
| Notebook de entrega | ❌ Pendiente (fase 8), a propósito — ver `03-proximos-pasos.md` |
| Documentación técnica | ✅ Este documento + `README.md` |
| Sección "dificultades encontradas" | ✅ Ver sección 9 más abajo |
| Presentación oral | ❌ Pendiente |
| Tests automáticos | ✅ `tests/` (sql_guard, config, introspección, herramientas del agente); falta un test automático contra la API real de un LLM (se verifica a mano) |

---

## 9. Dificultades encontradas y cómo se resolvieron

Esta sección es material directo para la defensa oral (la consigna pide identificar dificultades).

### 9.1 Dificultades de diseño / código

| Problema detectado | Solución |
|---|---|
| El "modo Agente" armaba un agente ReAct de LangGraph pero en realidad corría un pipeline fijo de 5 pasos que no lo usaba | Se conectó `create_react_agent` de verdad: el LLM decide en cada paso qué herramienta invocar |
| Los embeddings, incluso configurando Gemini, caían en un `HashingVectorizer` local (compara palabras, no significado) | Se eliminó ese fallback: los embeddings siempre son los del proveedor configurado, o la app no arranca |
| El guardrail de SQL bloqueaba por error consultas de lectura legítimas con `UNION`/`INTERSECT`/`EXCEPT` (en sqlglot no son `exp.Select`) | Se agregaron esos tipos de nodo AST a la clasificación de lectura |
| `INSERT` estaba prohibido sin excepción, en vez de pasar por aprobación humana como `UPDATE`/`DELETE` | Se reclasificó como `WRITE` (HITL), consistente con el resto de las escrituras |
| Auditoría y cola de aprobaciones eran diccionarios globales en memoria: se perdían al reiniciar y se compartían entre todas las sesiones de todos los usuarios | Se persistieron en SQLite (`audit_store.py`), separadas por `thread_id` de sesión |
| El esquema se cargaba pegando un `.sql`/`.json` a mano, o eligiendo entre dos modelos de datos fijos con sinónimos escritos a mano | La introspección lee siempre `DATABASE_URL` en vivo, y el contexto de negocio sale de `COMMENT ON TABLE/COLUMN` de la propia base — funciona con cualquier esquema |
| La app tenía un botón que ejecutaba `DROP SCHEMA CASCADE` sobre la base configurada en `.env`, y otro que aplicaba cualquier DDL subido sin pasar por el guardrail | Se eliminaron ambos: sembrar o modificar el esquema es una acción deliberada de consola, no un botón de la UI |
| Contar filas con `COUNT(*)` en cada tabla en cada arranque, lento en bases grandes | Se usa la estimación de `pg_class.reltuples` en Postgres |

### 9.2 Dificultades de puesta en marcha (probando en una máquina Windows real)

| Problema detectado | Solución |
|---|---|
| `uvloop` (dependencia transitiva) no tiene soporte para Windows y rompía `pip install -r requirements.txt` | Se le agregó el marcador de entorno `sys_platform != "win32"` para que se instale solo en Linux/Mac |
| El puerto `5432` del Postgres de `docker-compose.yml` chocaba con otros contenedores/Postgres locales ya corriendo en la máquina | Se lo hizo configurable con `POSTGRES_PORT` (default `5432`, sin romper a quien no lo necesita) |
| El modelo `gemini-2.5-flash` dejó de estar disponible para API keys nuevas de Google (`404 NOT_FOUND`) | Se actualizó el default sugerido en `.env.example` a `gemini-3.8-flash`; queda documentado que hay que revisar el modelo vigente antes de una demo |
| El diagrama SVG del esquema fallaba con `MODULE_NOT_FOUND` porque la dependencia de Node (`@softwaretechnik/dbml-renderer`) nunca se había declarado en un `package.json` ni se instalaba sola | Se agregó `package.json`/`package-lock.json` y se automatizó `npm install` en `start_app.bat` |

---

## 10. Documentación relacionada

- [`README.md`](../README.md): instalación, arquitectura resumida y decisiones de diseño.
- [`02-plan-de-desarrollo.md`](02-plan-de-desarrollo.md): plan de desarrollo original (registro
  histórico, ya ejecutado en su mayor parte).
- [`03-proximos-pasos.md`](03-proximos-pasos.md): qué queda pendiente hoy.
