# 🛡️ DB Copilot — Copiloto RAG & Agente SQL para bases de datos relacionales

> **TP2: Sistemas Inteligentes** — Universidad Tecnológica Nacional (UTN)
> Sistema inteligente para consultar, documentar y operar sobre una base de datos relacional
> mediante RAG y un agente de LangGraph con guardrails de seguridad y aprobación humana (Human-In-The-Loop).

> Documentación extendida en [`docs/`](docs/): estado del proyecto en
> [`docs/01-documentacion-actual.md`](docs/01-documentacion-actual.md) y el plan de trabajo en
> [`docs/02-plan-de-desarrollo.md`](docs/02-plan-de-desarrollo.md).

---

## 🎯 Caso de negocio

En las organizaciones, entender el modelo de datos de una base relacional y escribir SQL correcto
suele depender de pocas personas (ingenieros o DBAs que conocen la base "de memoria"), lo que genera
cuellos de botella para analistas y equipos de negocio.

**DB Copilot** resuelve esto con dos modos:

1. **Modo Documentación (RAG):** responde preguntas sobre la estructura de la base (tablas, columnas,
   relaciones, índices) sin ejecutar SQL, usando búsqueda semántica sobre el esquema.
2. **Modo Agente SQL:** un agente de LangGraph decide qué herramientas usar (buscar en el esquema,
   describir una tabla, ejecutar una lectura, proponer una escritura) para responder pedidos en
   lenguaje natural, con guardrails de seguridad y aprobación humana obligatoria para toda escritura.

---

## 🏗️ Arquitectura

```
                    Usuario (lenguaje natural)
                              │
              ┌───────────────┴────────────────┐
              ▼                                 ▼
   Modo Documentación (RAG)              Modo Agente SQL (LangGraph)
              │                                 │
    Retriever semántico (Chroma)      Agente ReAct con herramientas:
    sobre el esquema introspectado    list_tables, describe_table,
    en vivo desde DATABASE_URL        retrieve_schema, run_select, run_write
              │                                 │
     Síntesis con Gemini                Guardrails (sqlglot AST)
                                                 │
                                   ┌─────────────┴─────────────┐
                                   ▼                            ▼
                         SELECT permitido              INSERT/UPDATE/DELETE
                         (LIMIT inyectado)              → cola de aprobación
                                   │                     humana (HITL)
                          DataFrame a la UI                     │
                                                        Aprobado → ejecuta
                                                        Rechazado → cancela
                                          (todo queda en el audit log)
```

El esquema **siempre** se lee en vivo de `DATABASE_URL` (introspección con SQLAlchemy). No hay carga
manual de un `.sql`/`.json`: eso evitaba que el sistema respondiera sobre un esquema distinto del que
realmente consultaba.

---

## 📁 Estructura del proyecto

```
tp2-ia-utn/
├── db_copilot/
│   ├── config.py                 # .env, engine SQLAlchemy, LLM y embeddings de Gemini (sin fallback)
│   ├── schema_introspection.py   # Introspección en vivo del catálogo, docs NLP para el RAG, DBML/DDL
│   ├── rag.py                    # Vector store (Chroma) con embeddings de Gemini
│   ├── sql_guard.py              # Guardrails con sqlglot (AST): clasificación, LIMIT, bloqueo de DDL
│   ├── agent.py                  # Herramientas @tool, agente ReAct de LangGraph, HITL
│   ├── audit_store.py            # Auditoría y cola de aprobaciones persistidas en SQLite
│   └── app.py                    # App Streamlit (Chat, Esquema, Diagrama ER, Auditoría)
├── scripts/
│   ├── seed_demo.py              # Siembra la base de demo (15 tablas) — SOLO por consola, con confirmación
│   ├── _seed_enterprise_impl.py  # Implementación del sembrado (Faker)
│   └── test_stream_agent.py      # Script manual para ver los pasos del agente en vivo
├── sql/
│   └── complex_enterprise_schema.sql   # DDL de referencia de las 15 tablas de demo
├── tests/                         # pytest: sql_guard, config, introspección (sin red ni API)
├── notebooks/demo.ipynb          # Notebook de la cátedra (a rehacer para la entrega final)
├── material-catedra/             # Notebooks de la materia, no forman parte del proyecto
├── docs/                          # Documentación del estado del proyecto y plan de trabajo
├── render_dbml.js                # Renderiza el DBML a SVG (opcional, requiere Node.js)
├── requirements.txt
└── .env.example
```

`data/` (Chroma y el audit log en SQLite) se crea sola al importar `config.py` y está en `.gitignore`.

---

## 🚀 Puesta en marcha

### 1. Instalar dependencias

Requiere Python 3.10+.

```bash
pip install -r requirements.txt
```

Opcional, solo para renderizar el diagrama ER a SVG:

```bash
npm install @softwaretechnik/dbml-renderer
```

### 2. Configurar el `.env`

```bash
cp .env.example .env
```

Como mínimo hacen falta:

```env
DATABASE_URL=postgresql+psycopg2://usuario:password@localhost:5432/mi_base
GOOGLE_API_KEY=tu-api-key-de-gemini
```

Solo se usa **Google Gemini**: no hay soporte para OpenAI ni un vectorizador local de respaldo. Si falta
`GOOGLE_API_KEY`, la app **no arranca** (a propósito: preferimos un error claro antes que un modo
degradado sin embeddings semánticos).

### 3. (Opcional) Sembrar la base de demo

Si no tenés una base propia para probar, `scripts/seed_demo.py` crea el modelo de 15 tablas de
e-commerce con datos generados con Faker. **No es un botón de la app**: recrear el esquema de una base
de datos es una acción irreversible y deliberadamente no está a un click de distancia.

```bash
python scripts/seed_demo.py --url "sqlite:///data/ecommerce.db" --orders 1500
```

### 4. Ejecutar la app

```bash
streamlit run db_copilot/app.py
```

Se abre en `http://localhost:8501`. Desde ahí podés:
- alternar entre **Modo Agente** y **Modo Documentación (RAG)**;
- ver el esquema de la base en vivo, su diagrama ER y una muestra de cada tabla (todo de solo lectura);
- aprobar o rechazar las escrituras (`INSERT`/`UPDATE`/`DELETE`) que proponga el agente;
- consultar el log de auditoría completo.

---

## 🧠 Decisiones de diseño clave

### 1. Agente real de LangGraph, no un pipeline fijo
El modo Agente usa `create_react_agent` de LangGraph: el LLM decide en cada paso qué herramienta
invocar (`list_tables`, `describe_table`, `retrieve_schema`, `run_select`, `run_write`). La
auto-corrección ante un error de SQL no es un prompt especial aparte: `run_select` devuelve el error
del motor como texto y el mismo agente lo lee, corrige el SQL y reintenta.

### 2. Separación del canal de datos y el canal conversacional
`run_select` ejecuta la consulta y guarda el `DataFrame` completo para la interfaz; al LLM solo le
llega un resumen (cantidad de filas, columnas y una muestra de 2 filas). Evita transcribir miles de
filas en el prompt, con el costo, la latencia y el riesgo de alucinación que eso implica.

### 3. Guardrails con `sqlglot` (AST), no con expresiones regulares
`sql_guard.py` parsea el árbol de sintaxis de cada sentencia: exige que sea una única sentencia,
inyecta `LIMIT` en las lecturas que no lo tengan (incluye `UNION`/`INTERSECT`/`EXCEPT`/`WITH`), y
bloquea sin excepción `DROP`/`ALTER`/`CREATE`/`TRUNCATE`. `INSERT`/`UPDATE`/`DELETE` no se bloquean:
quedan retenidos para aprobación humana.

### 4. Human-in-the-Loop persistente
Toda escritura propuesta por el agente queda en una cola de aprobación (`data/audit.sqlite`) con un ID
único. Solo se ejecuta contra la base cuando un operador la aprueba explícitamente desde la interfaz.
A diferencia de la primera versión, esto y el log de auditoría sobreviven a un reinicio de la app y no
se comparten entre sesiones de distintos usuarios.

### 5. Esquema siempre en vivo, sin sinónimos escritos a mano
La introspección lee `COMMENT ON TABLE`/`COMMENT ON COLUMN` de la propia base como contexto de
negocio para el RAG, en vez de un diccionario de sinónimos fijo pensado para un único modelo de datos.
Esto permite apuntar `DATABASE_URL` a cualquier base y que el sistema siga funcionando.

### 6. Solo Gemini, con degradación explícita ante fallas
El LLM y los embeddings usan exclusivamente la API de Google Gemini. El respaldo ante un error 429/503
usa `.with_fallbacks(...)` de LangChain (un modelo Flash-Lite más liviano), en vez de detectar códigos
de error a mano. Si falta la API key, la aplicación no arranca: no hay fallback a un vectorizador local
sin significado semántico.

---

## 🧪 Tests

```bash
pytest
```

Los tests de `sql_guard`, `config` e introspección no requieren red ni credenciales (usan SQLite en
memoria y validan que las factories fallen con un error claro cuando falta configuración). No hay un
test automático contra la API real de Gemini: eso se verifica a mano con `scripts/test_stream_agent.py`.

---

## ⚠️ Notas para la defensa

- Los nombres de modelo de Gemini configurados en `.env.example` cambian con frecuencia; confirmarlos
  en [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models) antes de una
  demo importante.
- El notebook de entrega (`notebooks/demo.ipynb`) todavía corresponde a la versión anterior del
  proyecto y se va a rehacer al final, una vez cerrada la app (ver `docs/02-plan-de-desarrollo.md`,
  fase 8).
