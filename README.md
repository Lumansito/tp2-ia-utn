# 🛡️ DB Copilot — Copiloto RAG & Agente SQL para PostgreSQL

> **TP2: Sistemas Inteligentes** — Universidad Tecnológica Nacional (UTN)  
> Sistema inteligente para consulta, documentación y gestión operativa de bases de datos relacionales mediante RAG y Agentes LangGraph / LangChain con Guardrails de seguridad y Human-In-The-Loop.

---

## 🎯 Caso de Negocio y Objetivos

* **Problema:** En las organizaciones, comprender el modelo de datos de una base relacional y escribir consultas SQL correctas suele depender de ingenieros o DBAs que conocen la base "de memoria". Esto genera cuellos de botella constantes para analistas, equipos de negocio y desarrolladores.
* **Solución:** Un copiloto inteligente que:
  1. **Conoce la estructura (RAG sobre el Esquema):** Responde preguntas de arquitectura y relaciones sin necesidad de ejecutar consultas sobre los datos.
  2. **Opera de forma segura (Agente con Guardrails):** Traduce peticiones en lenguaje natural a SQL, inyecta límites preventivos, ejecuta consultas de lectura de inmediato y **retiene operaciones de modificación (UPDATE/DELETE)** hasta que un humano las apruebe explícitamente.
  3. **Separa el canal de datos del canal de texto:** Cuando se consultan grandes volúmenes (ej. 1000 filas), los datos se entregan directamente como DataFrame interactivo a la interfaz (Streamlit / Notebook) y no se pasan como texto al LLM, reduciendo costos, latencia y alucinaciones.

---

## 🏗️ Arquitectura del Sistema

```
                         [ Pregunta del Usuario ]
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
        [ Modo Esquema (RAG) ]             [ Modo Agente (SQL) ]
                  │                                   │
      ┌───────────┴───────────┐           ┌───────────┴───────────┐
      ▼                       ▼           ▼                       ▼
[ Retriever RAG ]    [ Síntesis LLM ]  [ RAG de Esquema ]   [ Generación SQL ]
(Chroma Vector Store) (Explicación)    (Tablas y FKs)              │
                                                                   ▼
                                                          [ Guardrails sqlglot ]
                                                          - Sentencia única
                                                          - Inyección de LIMIT
                                                          - Clasificación AST
                                                                   │
                                           ┌───────────────────────┴───────────────────────┐
                                           ▼                                               ▼
                                   [ SELECT Permitido ]                           [ UPDATE / DELETE ]
                                           │                                               │
                                 ┌─────────┴─────────┐                         [ Cola de Aprobación Humana ]
                                 ▼                   ▼                                     │
                        [ Canal de Datos ]   [ Canal de Texto ]                   ┌────────┴────────┐
                         (DataFrame a UI)     (Resumen 1 línea)                   ▼                 ▼
                                                                             [ APROBADO ]      [ RECHAZADO ]
                                                                             (Ejecuta en DB)   (Cancela acción)
```

---

## 📁 Estructura del Proyecto

```
utn-ia-tp2/
├── db_copilot/
│   ├── __init__.py
│   ├── config.py                 # Conexión SQLAlchemy, variables de entorno y fábrica LLM/Embeddings
│   ├── seed_data.py              # Generador Faker de 1200+ pedidos y tablas sintéticas
│   ├── schema_introspection.py   # Introspección SQLAlchemy inspect(), soporte DDL/JSON a NLP
│   ├── rag.py                    # Vector Store (Chroma), chunking, retriever y Modo Documentación
│   ├── sql_guard.py              # Guardrails con sqlglot: clasificación AST, LIMIT e inyecciones
│   ├── agent.py                  # Tools (@tool), LangGraph con Human-in-the-loop y separación de datos
│   └── app.py                    # Aplicación interactiva en Streamlit (Chat, DataFrames y Aprobaciones)
├── notebooks/
│   └── demo.ipynb                # Cuaderno Jupyter paso a paso (Entregable obligatorio con fundamentación)
├── sql/
│   └── schema_seed.sql           # DDL relacional (PostgreSQL / SQLite)
├── data/                         # Base SQLite local para demo inmediata y persistencia de Chroma
├── requirements.txt              # Dependencias fijadas y verificadas
└── README.md                     # Documentación general y guía de defensa
```

---

## 🚀 Puesta en Marcha

### 1. Instalación de Dependencias

Se requiere Python 3.10 o superior (verificado con Python 3.13):

```bash
pip install -r requirements.txt
```

### 2. Configuración de Variables de Entorno (Opcional)

Puedes crear un archivo `.env` en la raíz del proyecto o configurar las claves directamente en la interfaz gráfica de Streamlit:

```env
# Proveedor de LLM (OPENAI o GEMINI)
LLM_PROVIDER=OPENAI
OPENAI_API_KEY=tu_clave_de_openai_aqui
# O bien:
# LLM_PROVIDER=GEMINI
# GOOGLE_API_KEY=tu_clave_de_gemini_aqui

# Connection String a PostgreSQL (o se usa SQLite por defecto)
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/ecommerce_db
```

### 3. Ejecutar la Aplicación Interactiva (Streamlit)

```bash
streamlit run db_copilot/app.py
```

La app se abrirá en tu navegador (`http://localhost:8501`) y permite:
* Ingresar el **Connection String** de PostgreSQL o activar la base sintética local.
* Elegir el método de carga del esquema: **Introspección automática en vivo** o carga de archivo `.sql` / `.json`.
* Alternar con un clic entre **Modo Documentación (RAG)** y **Modo Agente SQL**.
* Ver los **DataFrames embebidos** interactivos con botón de descarga a CSV.
* Gestionar las **aprobaciones de escrituras** con botones Aprobar / Rechazar.
* Consultar la pestaña de **Auditoría (Audit Log)**.

### 4. Ejecutar el Notebook Entregable

Para visualizar la ejecución paso a paso del flujo teórico y práctico:

```bash
jupyter notebook notebooks/demo.ipynb
```

---

## 🧠 Decisiones de Diseño Clave (Para la Defensa Oral)

### 1. Separación del Canal de Datos vs. Canal Conversacional
* **Por qué:** Cuando se piden 1000 pedidos, si las 1000 filas se inyectan en el prompt del LLM para que las "reescriba", se consumen decenas de miles de tokens innecesarios, se ralentiza la aplicación y el LLM suele truncar o alucinar filas intermedias.
* **Nuestra arquitectura:** La herramienta `run_select` devuelve el objeto `pandas.DataFrame` directo a la capa visual (`st.dataframe(df)` o `display(df)`), y al LLM solo se le remite una síntesis técnica (cantidad de filas, nombres de columnas y muestra estadística) para que elabore un resumen conversacional de 1-2 líneas.

### 2. Guardrails Multinivel con `sqlglot`
* **Validación AST formal:** En lugar de relying en expresiones regulares frágiles, utilizamos `sqlglot` para parsear el árbol sintáctico del dialecto destino.
* **Defensa en profundidad:**
  1. *Sentencia única obligatoria:* Si la cadena contiene múltiples expresiones separadas por punto y coma (ej. `SELECT ...; DROP TABLE ...;`), se bloquea de inmediato.
  2. *Inyección de `LIMIT 500`:* Si un `SELECT` carece de límite, se le agrega automáticamente en el AST.
  3. *Rechazo tajante de DDL:* Operaciones `DROP`, `ALTER`, `CREATE` o `TRUNCATE` están deshabilitadas sin excepción.

### 3. Human-in-the-Loop para Mutaciones (`UPDATE` / `DELETE`)
* En entornos productivos, un agente no debe mutar datos sin supervisión.
* La herramienta `run_write` suspende la acción, le asigna un `action_id` y la encola como `PENDING`. Solo cuando un humano presiona "Aprobar", la sentencia se envía al motor, registrando quién, cuándo y cuántas filas se alteraron en el log de auditoría.

### 4. Introspección y Anclaje RAG (*Anti-Alucinaciones*)
* El agente tiene la instrucción mandatoria en su prompt de invocar `retrieve_schema` antes de estructurar cualquier consulta SQL.
* Esto ancla las referencias de columnas y relaciones foráneas al catálogo real, evitando errores sintácticos o uniones contra tablas inexistentes.
