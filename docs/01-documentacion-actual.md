# DB Copilot: documentación del estado actual

> **Nota (23/09/2026):** este documento describe el estado del proyecto **antes** del refactor (commit `ec1f291`). Se deja como referencia historica de los problemas detectados y por que se tomo cada decision. El estado real del codigo hoy esta en [`00-estado-de-implementacion.md`](00-estado-de-implementacion.md) y en el [`README.md`](../README.md) de la raiz.


> **Qué es este documento:** describe lo que el código hace **hoy** (commit `ec1f291`, 23/09/2026), no lo que dice el README. Cuando la documentación existente (`README.md`, `documentacion general del proyecto.md`) no coincide con el código, se aclara en la [sección 9](#9-diferencias-entre-la-documentación-existente-y-el-código).
>
> El plan de cambios está en [`02-plan-de-desarrollo.md`](02-plan-de-desarrollo.md).

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

---

## 2. Qué es DB Copilot

Un asistente que permite consultar una base de datos relacional (PostgreSQL o SQLite) en lenguaje natural. El caso de negocio: en las empresas, entender el modelo de datos y escribir SQL correcto depende de pocas personas (DBAs o seniors), y eso genera cuellos de botella.

Tiene dos modos de uso:

1. **Modo Documentación (RAG):** responde preguntas sobre la **estructura** de la base (tablas, columnas, relaciones, índices) sin ejecutar SQL.
2. **Modo Agente SQL:** convierte un pedido en SQL, lo valida con guardrails, lo ejecuta (lecturas) o lo deja pendiente de aprobación humana (escrituras) y muestra el resultado en una tabla.

---

## 3. Stack tecnológico

| Capa | Tecnología |
|---|---|
| LLM | Gemini (`langchain-google-genai`) u OpenAI (`langchain-openai`), elegido por `.env` |
| Embeddings | OpenAI `text-embedding-3-small` **o**, si no hay clave de OpenAI, `LocalHashEmbeddings` (HashingVectorizer de scikit-learn) |
| Vector store | ChromaDB (`langchain-chroma`), persistido en `data/chroma_db` |
| Orquestación | LangChain (LCEL en el modo RAG) y LangGraph (`create_react_agent`, **armado pero sin usar**, ver §6.3) |
| Base de datos | SQLAlchemy 2 + psycopg2 (PostgreSQL) o SQLite |
| Guardrails SQL | `sqlglot` (AST) con una alternativa por regex si `sqlglot` no está instalado |
| UI | Streamlit |
| Datos de prueba | Faker (`es_ES`) |
| Diagramas | DBML generado en Python, renderizado a SVG con Node (`@softwaretechnik/dbml-renderer`) |

---

## 4. Estructura del repositorio

```
tp2-ia-utn/
├── db_copilot/
│   ├── __init__.py
│   ├── config.py                 # .env, engine SQLAlchemy, fábricas de LLM y embeddings
│   ├── schema_introspection.py   # Lee el catálogo de la base → metadatos → textos para el RAG + DBML
│   ├── rag.py                    # Chroma: indexado, retriever balanceado, respuesta modo Documentación
│   ├── sql_guard.py              # Validación y clasificación de SQL con sqlglot
│   ├── agent.py                  # Herramientas @tool, pipeline del modo Agente, HITL, auditoría
│   ├── app.py                    # App Streamlit (5 pestañas)
│   ├── seed_enterprise.py        # Crea (DROP SCHEMA CASCADE) y llena el modelo de 15 tablas
│   └── seed_data.py              # Modelo alternativo de 4 tablas (lo usa el notebook)
├── sql/
│   ├── complex_enterprise_schema.sql   # DDL de las 15 tablas
│   └── schema_seed.sql                 # DDL de las 4 tablas
├── notebooks/demo.ipynb          # Notebook de demo (sin ejecutar, no llama al LLM)
├── render_dbml.js                # Script Node que pasa DBML a SVG
├── test_pipeline.py              # Script suelto: copia vieja del pipeline del agente
├── test_stream.py                # Script suelto: prueba del agente ReAct de LangGraph con streaming
├── NLP_1_Conceptos (1).ipynb     # Material de la cátedra (no es parte del proyecto)
├── NLP_3_langchain_conversaciones_rag_v2.ipynb   # Material de la cátedra
├── NLP_4_langchain_agentes.ipynb                 # Material de la cátedra
├── Trabajo Práctico N2.pdf       # Consigna
├── README.md
├── documentacion general del proyecto.md
├── requirements.txt
└── .env.example
```

`data/` (base SQLite y Chroma) se crea sola al importar `config.py` y está en `.gitignore`.

---

## 5. Configuración actual (`.env`)

| Variable | Uso actual | Valor por defecto si falta |
|---|---|---|
| `DATABASE_URL` | Conexión de SQLAlchemy | `postgresql+psycopg2://postgres:postgres@localhost:5432/ecommerce_db` |
| `LLM_PROVIDER` | `OPENAI`, `GEMINI` o `AUTO` | `AUTO` (elige según las claves que encuentre) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | LLM y embeddings de OpenAI | `gpt-4o-mini` |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | LLM de Gemini | `gemini-3.5-flash-lite` en `config.py`, pero la barra lateral de la app muestra `gemini-3.6-flash` como defecto (inconsistencia) |

Para levantarla: `pip install -r requirements.txt` y después `streamlit run db_copilot/app.py`.

> `requirements.txt` **no incluye** `langchain-chroma` ni `scikit-learn`, y el código importa los dos. En una instalación limpia la app falla.

---

## 6. Cómo funciona, módulo por módulo

### 6.1 `config.py`
- Carga `.env`, crea `data/` y `data/chroma_db/`.
- `get_engine(url)`: normaliza `postgresql://` a `postgresql+psycopg2://`. En SQLite pasa `check_same_thread=False`.
- `get_llm(provider, api_key, model_name, temperature=0)`:
  - en modo `AUTO` elige Gemini u OpenAI mirando el formato de las claves;
  - con Gemini intenta activar `thinking_config={"include_thoughts": True}` para poder mostrar el razonamiento del modelo.
- `get_embeddings()`: si el proveedor es OpenAI y hay clave real, usa `text-embedding-3-small`. **En cualquier otro caso (incluido usar Gemini) usa `LocalHashEmbeddings`**, un `HashingVectorizer` de 1024 dimensiones. No es un embedding semántico: compara palabras (hashing de tokens), no significado.

### 6.2 `schema_introspection.py`
- `introspect_database(engine)`: usa `sqlalchemy.inspect()` para leer tablas, columnas (tipo, nulabilidad, default), PK, FK e índices. Además hace un `SELECT COUNT(*)` por tabla y consulta la versión del motor.
- `parse_ddl_schema(sql)` y `parse_json_schema(json)`: arman los mismos metadatos a partir de un `.sql` o `.json` subido, sin conectarse a la base.
- `generate_natural_language_docs(meta)`: arma los documentos del RAG:
  - 1 documento del motor;
  - 1 por tabla (columnas, tipos, PK, cantidad de filas);
  - 1 por cada FK;
  - 1 por cada índice.
  - Cada documento lleva la metadata `tipo` (`motor | tabla | relacion | indice`) y `nombre`.
  - **Tiene un diccionario de sinónimos escrito a mano** (`synonyms_map`) solo para las 15 tablas del e-commerce de demo. Incluye la aclaración "customers no tiene columna `name`". Con otra base, esas pistas no existen.
- `generate_dbml(meta)` y `render_dbml_to_svg(dbml)`: generan el diagrama ER llamando a `node render_dbml.js`.

### 6.3 `rag.py`
- `index_schema_documents(docs)`: aplica `RecursiveCharacterTextSplitter` (700 caracteres, overlap 80), **resetea la colección** `db_schema_docs` y vuelve a indexar todo.
- `retrieve_schema_context(query, k=4)`: recuperación "balanceada":
  1. hasta `max(k,4)` documentos filtrando por `tipo=tabla`;
  2. hasta `max(k-1,3)` documentos filtrando por `tipo=relacion`;
  3. si no trae nada, una búsqueda sin filtro.

  Devuelve todo concatenado como texto con encabezados `[TABLA: x]`.
- `answer_schema_question(query)`: **modo Documentación**. Cadena LCEL `ChatPromptTemplate | llm | StrOutputParser` con la instrucción de responder solo con el contexto recuperado. Si el LLM falla, devuelve el contexto crudo con una nota.

### 6.4 `sql_guard.py`: `validate_and_classify_sql(sql, default_limit=500, dialect)`

| Entrada | Clasificación | Qué hace |
|---|---|---|
| Vacío o con error de sintaxis | `INVALID` | Rechaza |
| Más de una sentencia (`;`) | `FORBIDDEN` | Rechaza |
| `SELECT` (incluye `WITH ... SELECT`) | `SELECT` | Si no tiene `LIMIT`, le agrega `LIMIT 500` en el AST |
| `UPDATE` / `DELETE` | `WRITE` | Válido. Si no tiene `WHERE`, agrega una advertencia |
| `DROP`, `ALTER`, `CREATE`, **`INSERT`**, `TRUNCATE`, `Command` | `FORBIDDEN` | Rechaza |
| Cualquier otro nodo, **incluido `UNION`/`INTERSECT`/`EXCEPT`** | `FORBIDDEN` | Rechaza. En sqlglot, `UNION` es `exp.Union`, no `exp.Select`, así que hoy se bloquean consultas de lectura legítimas |

Si `sqlglot` no está instalado, usa una alternativa por **regex** (mira la primera palabra y si hay `;`). Esto contradice el argumento de "no usamos regex" que da la documentación.

### 6.5 `agent.py`
- **Estado global en memoria** (se pierde al reiniciar y es compartido por todos los usuarios de Streamlit):
  - `_context_store`: último DataFrame, último SQL, escritura pendiente;
  - `_pending_writes`: la cola de escrituras pendientes;
  - `_audit_log`: el log de auditoría.
- **Herramientas `@tool`:**
  - `retrieve_schema(query)`: llama al retriever;
  - `run_select(sql)`: guardrail → ejecuta → guarda el DataFrame y **devuelve al LLM solo un resumen** (filas, columnas y 2 filas de muestra);
  - `run_write(sql)`: guardrail → encola como `PENDING` con un id de 8 caracteres. No ejecuta.
- `approve_pending_write(id, approve, operator)`: si se aprueba, ejecuta en una transacción (`engine.begin()`) y registra `rowcount`. Si se rechaza, lo marca `REJECTED`. En los dos casos lo audita.
- `execute_copilot_step_by_step(query, engine, llm)`: **esto es lo que corre de verdad en el modo Agente.** Es un **pipeline fijo** de 5 fases, cada una cronometrada (timeline):
  1. **RAG:** `retrieve_schema_context(query, k=4)`.
  2. **LLM:** un prompt que pide responder `TIPO: SELECT|WRITE|CONCEPTUAL / SQL: ... / EXPLICACION: ...`. El SQL se parsea línea por línea y, si no viene en ese formato, se busca un bloque ```` ```sql ````. Si la API devuelve 429/503, se reintenta con `gemini-3.5-flash-lite` (**también cuando el proveedor configurado es OpenAI**).
  3. **Guardrail:** `validate_and_classify_sql`.
  4. **Ejecución:**
     - `SELECT`: se ejecuta con pandas. Si falla, hay **una** vuelta de **auto-corrección**: se le manda al LLM el SQL, el error y el esquema, y se re-valida y re-ejecuta. El prompt de corrección tiene escrita a mano la pista `c.name → first_name/last_name`, que es propia de la base de demo.
     - `WRITE`: se encola para aprobación humana (HITL).
  5. **Síntesis:** la respuesta final es la `EXPLICACION` que dio el LLM en el paso 2. No hay una segunda llamada que resuma el resultado real.
- `SYSTEM_PROMPT`: instrucciones para el agente ReAct (usar `retrieve_schema` antes de escribir SQL, no transcribir filas, etc.).
- `DBCopilot`:
  - en `__init__` arma `create_react_agent(llm, tools, SYSTEM_PROMPT, InMemorySaver)`, pero **`ask()` nunca lo usa**. Solo lo prueba `test_stream.py`;
  - `ask(question, mode="schema")`: RAG y `answer_schema_question`, con timeline;
  - `ask(question, mode="agent")`: llama a `execute_copilot_step_by_step`.

### 6.6 `app.py` (Streamlit)
- **Arranque (`initialize_system`)**: `get_engine()` con `DATABASE_URL` → introspección (o parseo de un archivo subido) → documentos NLP → `get_embeddings()` → indexado en Chroma → `DBCopilot`. Si algo falla, guarda el error y la barra lateral muestra "🔴 Error de Conexión".
- **Barra lateral:**
  - estado (motor, host, proveedor, modelo);
  - botón **"💥 Tumbar y Recrear Base Completa"** (`DROP SCHEMA public CASCADE` sobre la base del `.env`);
  - botón "Reindexar esquema";
  - uploader de `.sql`/`.json`.
- **Banner:** escrituras pendientes con los botones ✅ Aprobar / ❌ Rechazar.
- **Pestañas:**
  1. **Chat:** selector de modo, historial, SQL ejecutado, DataFrame con descarga CSV, "thinking" y timeline de fases.
  2. **Carga y gestión de esquema:** elegir el esquema de 15 o de 4 tablas o subir un `.sql`; "Aplicar a la base" (ejecuta el DDL partido por `;`), "Cargar solo en RAG", "Recrear base y RAG".
  3. **Diagrama ER (DBML/SVG).**
  4. **DDL y explorador de tablas** (muestra 10 filas de la tabla elegida).
  5. **Audit log.**

### 6.7 Datos de demo
- `seed_enterprise.py`: modelo de e-commerce de **15 tablas** (departments, employees, warehouses, suppliers, categories con auto-referencia, products, inventory, customers, customer_addresses, promotions, orders, order_items, payments, shipments, product_reviews). Hace `DROP SCHEMA public CASCADE` y la app lo llena con 150 órdenes.
- `seed_data.py`: modelo de **4 tablas** (customers, products, orders, order_items). El notebook lo usa con 1200 órdenes.

---

## 7. Flujos de punta a punta (como están hoy)

**Modo Documentación:** pregunta → retriever de Chroma (tablas + relaciones) → prompt LCEL → Gemini/OpenAI → respuesta en texto. No toca la base.

**Modo Agente, lectura:** pregunta → RAG → el LLM genera `TIPO/SQL/EXPLICACION` → sqlglot (y `LIMIT 500` si falta) → pandas `read_sql` → DataFrame a la UI → se muestra la explicación que generó el LLM *antes* de ver los datos.

**Modo Agente, error de SQL:** falla la ejecución → prompt de corrección (SQL + error + esquema) → nuevo SQL → sqlglot → reintento (una sola vez) → si vuelve a fallar, mensaje de error prolijo.

**Modo Agente, escritura:** `UPDATE`/`DELETE` → queda `PENDING` en memoria → el operador aprueba en la UI → se ejecuta en una transacción → queda auditado con las filas afectadas.

**Bloqueo:** `DROP`/`ALTER`/`INSERT`/varias sentencias → `FORBIDDEN` → mensaje de bloqueo. **Ojo:** en el pipeline real los bloqueos **no se registran en el audit log**. Solo lo hacen las herramientas `run_select`/`run_write`, que el pipeline no usa.

---

## 8. Estado de los entregables

| Entregable | Estado |
|---|---|
| App funcional | ✅ Funciona con clave y base configuradas. Tiene los problemas de la §10 |
| Notebook | ⚠️ Existe pero **no está ejecutado**, **no llama al LLM** y probablemente falle el `import db_copilot` al abrirlo desde `notebooks/`. Se va a rehacer al final (ver el plan) |
| Documentación | ⚠️ Extensa, pero con afirmaciones que no coinciden con el código (§9) |
| Sección "dificultades" | ❌ No existe |
| Presentación oral | ❌ No existe |
| Tests | ❌ Solo hay scripts sueltos, sin asserts |

---

## 9. Diferencias entre la documentación existente y el código

| La documentación dice | El código hace |
|---|---|
| "Agentes LangGraph" que deciden qué herramienta usar | El modo Agente es un **pipeline fijo**. El agente ReAct se construye y no se usa |
| El agente "invoca `retrieve_schema` antes de cada consulta" (prompt obligatorio) | El pipeline llama al retriever directamente. El `SYSTEM_PROMPT` no se usa |
| Guardrails sin regex | Hay una alternativa por regex si falta `sqlglot` |
| Se bloquean solo los DDL | También se bloquean `INSERT` y `UNION` |
| Todo intento bloqueado queda en la auditoría | Los bloqueos del pipeline no se auditan |
| El LLM resume los resultados después de ejecutar | La "respuesta" es la explicación que dio el LLM antes de ejecutar |
| Fallback de embeddings "solo si falla la API" | Con Gemini **siempre** se usa HashingVectorizer |
| El notebook usa 1200 órdenes y 4 tablas, la app usa 15 tablas | Hay dos modelos de datos distintos según dónde se mire |
| Links `file:///c:/proyectos/tp2-ia-utn/...` | Esa ruta no existe en este equipo |
| Se "requiere" Python 3.10+ con las dependencias de `requirements.txt` | Faltan `langchain-chroma` y `scikit-learn` |

---

## 10. Problemas y deuda técnica detectados

1. **Funcionalidad o seguridad**
   - `UNION`/`INTERSECT`/`EXCEPT` quedan bloqueados (falso positivo del guardrail).
   - El botón "Tumbar y Recrear Base" hace `DROP SCHEMA public CASCADE` sobre **la base que esté en `.env`**, aunque sea una base real.
   - "Aplicar SQL a la base" ejecuta cualquier DDL subido, partido por `;`, sin pasar por el guardrail.
   - El fallback a Gemini aparece aunque se haya elegido OpenAI.
2. **Generalidad:** los sinónimos y la pista de corrección `c.name` están escritos a mano para la base de demo. Con otra base del `.env`, el RAG pierde contexto de negocio.
3. **Marco teórico:** con Gemini los embeddings no son semánticos (HashingVectorizer). El "agente" no es un agente.
4. **Estado:** la cola HITL y la auditoría son globales y viven en memoria. Se pierden al reiniciar y se comparten entre sesiones.
5. **Rendimiento:** la introspección hace `COUNT(*)` en cada tabla. En una base grande el arranque es lento.
6. **Repo:**
   - `requirements.txt` está incompleto;
   - hay scripts sueltos (`test_*.py`) y notebooks de la cátedra en la raíz;
   - hay mezcla de finales de línea LF/CRLF: `git status` muestra 23 archivos modificados sin cambios reales;
   - `test_pipeline.py` duplica el código de `agent.py`.
