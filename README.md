# 🛡️ DB Copilot — Copiloto RAG & Agente SQL para bases de datos relacionales

> **TP2: Sistemas Inteligentes** — Universidad Tecnológica Nacional (UTN)
> Sistema inteligente para consultar, documentar y operar sobre una base de datos relacional
> mediante RAG y un agente de LangGraph con guardrails de seguridad y aprobación humana (Human-In-The-Loop).

> Documentación extendida en [`docs/`](docs/): arquitectura detallada en
> [`docs/01-documentacion-actual.md`](docs/01-documentacion-actual.md) y qué falta en
> [`docs/03-proximos-pasos.md`](docs/03-proximos-pasos.md).

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
     Síntesis con el LLM configurado     Guardrails (sqlglot AST)
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
│   ├── config.py                 # .env, engine SQLAlchemy, LLM y embeddings (OpenAI o Gemini)
│   ├── schema_introspection.py   # Introspección en vivo del catálogo, docs NLP para el RAG, DBML/DDL
│   ├── rag.py                    # Vector store (Chroma) con los embeddings configurados
│   ├── sql_guard.py              # Guardrails con sqlglot (AST): clasificación, LIMIT, bloqueo de DDL
│   ├── agent.py                  # Herramientas @tool, agente ReAct de LangGraph, HITL
│   ├── audit_store.py            # Auditoría y cola de aprobaciones persistidas en SQLite
│   └── app.py                    # App Streamlit (Chat, Esquema, Diagrama ER, Auditoría)
├── scripts/
│   ├── generate_demo_sql.py      # Genera el SQL de la base de demo (Faker, seed fijo)
│   └── verify_demo_db.py         # Verifica que la base de demo de Docker haya cargado bien
├── docker/
│   └── init/01_schema_and_seed.sql   # Salida de generate_demo_sql.py; la corre Postgres solo al iniciar
├── docker-compose.yml             # Postgres con la base de demo precargada (puerto configurable)
├── tests/                         # pytest: sql_guard, config, introspección, herramientas del agente
├── notebooks/demo.ipynb          # Pendiente: se rehace al final, para la entrega (ver docs/03)
├── docs/                          # Documentación de arquitectura, estado y próximos pasos
├── render_dbml.js                # Renderiza el DBML a SVG (Node.js + @softwaretechnik/dbml-renderer)
├── package.json / package-lock.json   # Dependencia de Node de render_dbml.js
├── start_app.bat                 # Windows: venv, dependencias, Docker, Node y levanta la app
├── requirements.txt
└── .env.example
```

`data/` (Chroma y el audit log en SQLite) se crea sola al importar `config.py` y está en `.gitignore`.

---

## 🚀 Puesta en marcha

### Opción rápida (Windows): `start_app.bat`

Para no tener que instalar nada a mano, en Windows alcanza con hacer doble clic en
[`start_app.bat`](start_app.bat) (o correrlo desde una consola). El script:

1. Verifica que `python` esté instalado.
2. Crea un entorno virtual en `.venv` (la primera vez) y lo activa.
3. Instala/actualiza las dependencias de `requirements.txt`.
4. Si no existe `.env`, lo crea a partir de `.env.example` y lo abre en el Bloc de notas para
   que completes `LLM_PROVIDER`, `LLM_API_KEY`, etc. (avisa y no continúa si te olvidaste de
   cambiar la clave de ejemplo o la dejaste vacía).
5. Si encuentra Docker, levanta la base de datos con `docker compose up -d` (precargada con datos
   de demo — ver más abajo). Si tu `DATABASE_URL` apunta a otra base, este paso se puede ignorar.
6. Si encuentra Node.js y falta `node_modules`, corre `npm install` (dependencia opcional para el
   diagrama SVG del esquema).
7. Levanta la app con `streamlit run db_copilot/app.py` en `http://localhost:8501`.

Si preferís hacerlo a mano, o estás en Linux/Mac, seguí con la opción manual.

### Opción manual

#### 1. Instalar dependencias

Requiere Python 3.10+.

```bash
pip install -r requirements.txt
```

Opcional, solo para renderizar el diagrama ER a SVG (requiere Node.js):

```bash
npm install
```

#### 2. Configurar el `.env`

```bash
cp .env.example .env
```

`LLM_PROVIDER` acepta **`OPENAI`** o **`GEMINI`**: solo hace falta configurar el proveedor que vayas a
usar (no ambos). Como mínimo:

```env
DATABASE_URL=postgresql+psycopg2://usuario:password@localhost:5432/mi_base

LLM_PROVIDER=GEMINI
LLM_API_KEY=tu-api-key
LLM_MODEL=gemini-3.8-flash
EMBEDDING_MODEL=models/gemini-embedding-001
```

(Para OpenAI: `LLM_PROVIDER=OPENAI`, `LLM_MODEL=gpt-4o-mini`, `EMBEDDING_MODEL=text-embedding-3-small`,
por ejemplo). Si falta cualquiera de estas variables, la app **no arranca** con un error claro
(a propósito: preferimos eso antes que un modo degradado).

> Los nombres de modelo cambian con el tiempo (a nosotros ya nos pasó: `gemini-2.5-flash` dejó de
> estar disponible para claves nuevas). Si el arranque tira un error `NOT_FOUND` o `model no longer
> available`, confirmá el nombre vigente en la documentación del proveedor y actualizá `LLM_MODEL`.

#### 3. Base de datos: la tuya, o la de demo con Docker

Si ya tenés una base propia, apuntá `DATABASE_URL` a ella y listo — no hace falta nada más de esta
sección.

Si no tenés una base para probar, `docker-compose.yml` levanta un Postgres con una base de demo de
e-commerce **ya cargada** (categorías, productos, clientes, órdenes, ítems y pagos, generados con
Faker):

```bash
docker compose up -d
```

La primera vez que el contenedor arranca con el volumen vacío, Postgres corre automáticamente
`docker/init/01_schema_and_seed.sql` (generado por `scripts/generate_demo_sql.py`). Para confirmar que
cargó bien:

```bash
python scripts/verify_demo_db.py
```

Si el puerto `5432` ya está ocupado en tu máquina (otro Postgres local, u otro proyecto con Docker),
definí `POSTGRES_PORT` en tu `.env` (por ejemplo `5433`) y actualizá el puerto en `DATABASE_URL`
también.

#### 4. Ejecutar la app

```bash
streamlit run db_copilot/app.py
```

Se abre en `http://localhost:8501`. Desde ahí podés:
- alternar entre **Modo Agente** y **Modo Documentación (RAG)**;
- ver el esquema de la base en vivo, su diagrama ER y el DDL reconstruido de cada tabla (todo de
  solo lectura);
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
Toda escritura propuesta por el agente queda en una cola de aprobación (`data/audit.sqlite`, ver
`audit_store.py`) con un ID único. Solo se ejecuta contra la base cuando un operador la aprueba
explícitamente desde la interfaz. Auditoría y cola sobreviven a un reinicio de la app y no se
comparten entre sesiones de distintos usuarios (separadas por `thread_id`).

### 5. Esquema siempre en vivo, sin sinónimos escritos a mano
La introspección lee `COMMENT ON TABLE`/`COMMENT ON COLUMN` de la propia base como contexto de
negocio para el RAG, en vez de un diccionario de sinónimos fijo pensado para un único modelo de datos.
Esto permite apuntar `DATABASE_URL` a cualquier base y que el sistema siga funcionando.

### 6. Proveedor de LLM configurable, sin degradación silenciosa
`config.py` es genérico: `LLM_PROVIDER` elige entre Gemini y OpenAI, y solo hace falta la clave del
proveedor que se vaya a usar. Si falta cualquier variable de configuración (proveedor, clave, modelo),
la aplicación **no arranca** — no hay fallback a un vectorizador local sin significado semántico.

### 7. Base de demo reproducible en Docker
Para que cualquiera del equipo pueda probar la app sin armar su propia base, `docker-compose.yml`
precarga un Postgres con datos de demo generados de forma determinística (Faker con seed fijo). Quien
ya tenga su base solo cambia `DATABASE_URL` y no necesita este contenedor.

---

## 🧪 Tests

```bash
pytest
```

Los tests de `sql_guard`, `config`, introspección y las herramientas del agente (`tests/`) no requieren
red ni credenciales: usan SQLite en memoria y validan que las factories fallen con un error claro
cuando falta configuración, y que los guardrails y el flujo de aprobación (HITL) funcionen de punta a
punta sin un LLM real. No hay un test automático contra la API real de un LLM: eso se prueba a mano
corriendo la app.

---

## ⚠️ Notas para la defensa

- Los nombres de modelo (Gemini u OpenAI) cambian con frecuencia; confirmá el que tengas en
  `LLM_MODEL` antes de una demo importante (ver la nota en la sección de `.env` más arriba).
- El notebook de entrega (`notebooks/demo.ipynb`) todavía corresponde a una versión anterior del
  proyecto y se va a rehacer al final, una vez cerrada la app — ver
  [`docs/03-proximos-pasos.md`](docs/03-proximos-pasos.md).
- Detalle de arquitectura módulo por módulo, y las dificultades encontradas durante el desarrollo
  (útiles para la defensa oral), están en [`docs/01-documentacion-actual.md`](docs/01-documentacion-actual.md).
