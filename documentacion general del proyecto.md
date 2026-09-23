# 🛡️ DB Copilot — Documentación General del Proyecto & Arquitectura Técnica

> **TP2: Sistemas Inteligentes** — Universidad Tecnológica Nacional (UTN)  
> **Proyecto:** DB Copilot — Copiloto RAG & Agente SQL Autónomo con Guardrails y Human-In-The-Loop.  
> **Autores/Entorno:** Python 3.10+ (verificado en Python 3.13), PostgreSQL 16 / SQLite, LangChain, LangGraph, ChromaDB, sqlglot, Streamlit.

---

## 📑 Tabla de Contenidos
1. [Introducción & Caso de Negocio (El "Por Qué")](#1-introducción--caso-de-negocio-el-por-qué)
2. [Arquitectura General del Sistema & Flujo End-to-End](#2-arquitectura-general-del-sistema--flujo-end-to-end)
3. [Charla de Arquitectura: Decisiones de Diseño Clave & Trade-Offs](#3-charla-de-arquitectura-decisiones-de-diseño-clave--trade-offs)
   - [3.1. Separación de Canales: Canal de Datos vs. Canal Conversacional](#31-separación-de-canales-canal-de-datos-vs-canal-conversacional)
   - [3.2. Guardrails Multinivel con Parser AST (`sqlglot`)](#32-guardrails-multinivel-con-parser-ast-sqlglot)
   - [3.3. Human-in-the-Loop (HITL) para Operaciones de Modificación](#33-human-in-the-loop-hitl-para-operaciones-de-modificación)
   - [3.4. Bucle de Auto-Corrección Reflexiva (*Self-Healing SQL Loop*)](#34-bucle-de-auto-corrección-reflexiva-self-healing-sql-loop)
   - [3.5. Resiliencia, Fallbacks Locales y Multi-Proveedor de LLM/Embeddings](#35-resiliencia-fallbacks-locales-y-multi-proveedor-de-llmembeddings)
   - [3.6. DBML Dinámico y Renderizado Vectorial SVG](#36-dbml-dinámico-y-renderizado-vectorial-svg)
4. [Desglose Módulo por Módulo](#4-desglose-módulo-por-módulo)
   - [`config.py`](#configpy)
   - [`schema_introspection.py`](#schema_introspectionpy)
   - [`rag.py`](#ragpy)
   - [`sql_guard.py`](#sql_guardpy)
   - [`agent.py`](#agentpy)
   - [`app.py`](#apppy)
   - [`seed_enterprise.py` & `seed_data.py`](#seed_enterprisepy--seed_datapy)
5. [Modelo de Datos Empresarial (15 Tablas Relacionadas)](#5-modelo-de-datos-empresarial-15-tablas-relacionadas)
6. [Flujos de Ejecución Detallados (Paso a Paso con Diagramas de Secuencia)](#6-flujos-de-ejecución-detallados-paso-a-paso-con-diagramas-de-secuencia)
   - [Caso A: Consulta de Documentación y Arquitectura (RAG Puro)](#caso-a-consulta-de-documentación-y-arquitectura-rag-puro)
   - [Caso B: Consulta Operacional de Lectura (`SELECT`)](#caso-b-consulta-operacional-de-lectura-select)
   - [Caso C: Consulta con Error de Columna y Auto-Corrección](#caso-c-consulta-con-error-de-columna-y-auto-corrección)
   - [Caso D: Solicitud de Escritura (`UPDATE`/`DELETE`) y Aprobación Humana](#caso-d-solicitud-de-escritura-updatedelete-y-aprobación-humana)
   - [Caso E: Detección y Bloqueo de Sentencias Prohibidas o Maliciosas](#caso-e-detección-y-bloqueo-de-sentencias-prohibidas-o-maliciosas)
7. [Observabilidad, Profiling y Métricas en Tiempo Real](#7-observabilidad-profiling-y-métricas-en-tiempo-real)
8. [Guía de Instalación, Configuración y Despliegue](#8-guía-de-instalación-configuración-y-despliegue)
9. [Defensa Oral del Proyecto (Tips & Preguntas Frecuentes de Examen)](#9-defensa-oral-del-proyecto-tips--preguntas-frecuentes-de-examen)

---

## 1. Introducción & Caso de Negocio (El "Por Qué")

### La Problemática Real en la Industria
En cualquier organización moderna que gestiona volúmenes medianos o grandes de información en bases de datos relacionales (como PostgreSQL, MySQL o SQL Server), surgen dos fricciones operativas críticas:

1. **La barrera del conocimiento del modelo de datos:** Los modelos de datos empresariales reales no son de 2 tablas; superan las 15, 30 o 100 tablas, con nombres técnicos codificados, claves foráneas compuestas, reglas de negocio implícitas y estados transaccionales. Comprender qué tabla une con cuál suele depender exclusivamente de ingenieros sénior o DBAs que guardan el esquema "en la cabeza". Analistas de negocio, ejecutivos y desarrolladores junior quedan bloqueados esperando respuestas.
2. **El peligro de delegar SQL a un LLM sin salvaguardas:** Si se conecta un Modelo de Lenguaje (LLM) directamente a una base de datos mediante un script genérico tipo *"Text-to-SQL"*, el sistema resulta inviable para producción:
   - **Alucinación de columnas y tablas:** El LLM asume nombres habituales (ej. busca `customers.name` cuando en realidad se diseñó `customers.first_name` y `customers.last_name`).
   - **Inyecciones y borrados catastróficos:** Una instrucción ambigua o un prompt injection podría inducir un `DROP TABLE` o un `UPDATE` sin cláusula `WHERE`, corrompiendo la base.
   - **Saturación por volumen de datos:** Si una consulta retorna 2.000 filas y se inyectan en el prompt del LLM para que las "muestre", se agota la ventana de contexto, se disparan los costos en miles de tokens, sube la latencia a decenas de segundos y el modelo alucina datos intermedios.

### La Solución: DB Copilot
**DB Copilot** fue concebido y desarrollado para resolver esta dualidad mediante una arquitectura robusta de **Sistemas Inteligentes**:
* **Modo Documentación (RAG sobre el Esquema):** Permite consultar la estructura, significado de entidades, claves primarias, foráneas e índices mediante búsqueda semántica vectorial sobre ChromaDB, **sin tocar la base de datos ni emitir SQL**.
* **Modo Agente SQL (Copilot Operacional Seguro):** Traduce lenguaje natural a SQL anclándose primero al catálogo real (vía RAG), pasando por **guardrails basados en el Árbol de Sintaxis Abstracta (AST)**, ejecutando lecturas con inyección preventiva de límites, separando el canal de datos del canal de texto, y **reteniendo cualquier modificación en una cola de aprobación humana obligatoria (*Human-In-The-Loop*)**.

---

## 2. Arquitectura General del Sistema & Flujo End-to-End

El sistema sigue una arquitectura de capas bien delimitadas, donde cada componente asume una única responsabilidad bien definida:

```mermaid
flowchart TD
    subgraph UI ["Capa de Presentación e Interacción (Streamlit / Notebook)"]
        UserPrompt["Usuario ingresa petición en Lenguaje Natural"]
        Selector["Selector de Modo: Documentación (RAG) vs. Agente SQL"]
        UI_DF["Visualizador Interactivo de DataFrames + Botón CSV"]
        UI_Approval["Panel de Aprobación Humana (Aprobar / Rechazar)"]
        UI_Audit["Panel de Auditoría (Audit Log)"]
        UI_Profiler["Métricas de Tiempo y Thinking del LLM"]
    end

    subgraph RAG_Layer ["Capa de Conocimiento Semántico (RAG Local)"]
        Introspector["Introspección SQLAlchemy inspect() / DDL / JSON"]
        NLP_Gen["Generador de Documentos NLP con Sinónimos"]
        ChromaStore[("ChromaDB Vector Store")]
        Retriever["Retriever Semántico Ponderado (Tablas + Relaciones)"]
    end

    subgraph Agent_Layer ["Capa de Orquestación y Razonamiento (LangGraph / LangChain)"]
        CopilotController["Controlador DBCopilot"]
        PromptAgent["Prompt con Anclaje Obligatorio al Esquema"]
        LLM["Modelo LLM (Gemini 3.5/3.6 / OpenAI GPT-4o-mini)"]
        SelfHealing["Módulo de Auto-Corrección Reflexiva"]
    end

    subgraph Guard_Layer ["Capa de Seguridad y Guardrails (sqlglot AST)"]
        AST_Parser["Parser de Dialecto SQL (PostgreSQL / SQLite)"]
        Rule_Single["Regla: Sentencia Única (Anti Multi-Statement)"]
        Rule_Limit["Regla: Inyección Automática de LIMIT 500"]
        Rule_Classify{"Clasificación AST"}
        Rule_Forbidden["Bloqueo DDL/DCL (DROP, ALTER, CREATE, TRUNCATE)"]
    end

    subgraph Data_Layer ["Capa de Datos y Ejecución Transaccional"]
        HITL_Queue[("Cola de Aprobaciones PENDING en Memoria")]
        DBEngine[("Motor Relacional (PostgreSQL / SQLite)")]
        AuditEngine[("Registro Inmutable de Auditoría")]
    end

    %% Conexiones de Flujo
    UserPrompt --> Selector
    Selector -->|Modo Documentación| Retriever
    Retriever --> ChromaStore
    Retriever --> LLM
    LLM -->|Respuesta Conceptual| UI

    Selector -->|Modo Agente SQL| CopilotController
    CopilotController --> Retriever
    Retriever --> PromptAgent
    PromptAgent --> LLM
    LLM -->|Candidato SQL| AST_Parser

    AST_Parser --> Rule_Single
    Rule_Single --> Rule_Limit
    Rule_Limit --> Rule_Classify

    Rule_Classify -->|FORBIDDEN / DDL| Rule_Forbidden
    Rule_Forbidden -->|Error Bloqueado| AuditEngine
    Rule_Forbidden --> UI

    Rule_Classify -->|SELECT| DBEngine
    DBEngine -->|Fallo SQL| SelfHealing
    SelfHealing -->|Prompt Corrector + Error| LLM
    DBEngine -->|Éxito: DataFrame| UI_DF
    DBEngine -->|Muestra + Totales| LLM
    LLM -->|Resumen 1 línea| UI

    Rule_Classify -->|UPDATE / DELETE| HITL_Queue
    HITL_Queue --> UI_Approval
    UI_Approval -->|Aprobado por Operador| DBEngine
    UI_Approval -->|Rechazado| AuditEngine
    DBEngine --> AuditEngine
```

---

## 3. Charla de Arquitectura: Decisiones de Diseño Clave & Trade-Offs

Esta sección profundiza en las razones técnicas, desafíos de ingeniería y compromisos (*trade-offs*) adoptados durante la construcción de DB Copilot.

### 3.1. Separación de Canales: Canal de Datos vs. Canal Conversacional

#### ⚠️ El Problema Común
En implementaciones ingenuas de agentes SQL, la salida de la base de datos se convierte en una cadena de texto (ej. JSON o texto plano delimitado por tabulaciones) y se reinyecta en el prompt del LLM con una instrucción tipo: *"Aquí están los resultados de la base de datos, preséntaselos al usuario"*.

Si la consulta devuelve 1.000 órdenes de compra:
1. **Consumo masivo de tokens:** 1.000 filas con 8 columnas ocupan aproximadamente 30.000 tokens de entrada y salida.
2. **Latencia inadmisible:** El LLM tarda entre 15 y 40 segundos en generar esa enorme salida textual.
3. **Pérdida de fidelidad (Alucinación de truncamiento):** Los LLMs no son motores de renderizado. En la fila 150 suelen escribir `... [omitiendo filas 151 a 980] ...` o inventar valores numéricos intermedios.
4. **Costo financiero innecesario:** En APIs de pago por token, cada consulta de analítica costaría fracciones significativas de dólar.

#### 💡 Nuestra Solución Arquitectónica
Se implementó un desacoplamiento estricto en la herramienta [`run_select`](file:///c:/proyectos/tp2-ia-utn/db_copilot/agent.py#L77-L129):
* **Canal de Datos (Data Path):** La consulta se ejecuta mediante SQLAlchemy y se almacena directamente como un `pandas.DataFrame` estructurado en memoria (`_context_store["last_dataframe"]`). Este objeto viaja directamente al componente de interfaz gráfica [`st.dataframe(df)`](file:///c:/proyectos/tp2-ia-utn/db_copilot/app.py#L391-L400) de Streamlit o a `display(df)` en Jupyter Notebook. No toca los tokens del LLM. Incluye botón interactivo de descarga a CSV.
* **Canal Conversacional (Control Path):** Al LLM únicamente se le retorna un paquete mínimo de metadatos:
  ```python
  f"Consulta ejecutada con éxito.\n"
  f"- Filas obtenidas: {len(df)}\n"
  f"- Columnas: [{cols_summary}]\n"
  f"- Muestra inicial (2 filas): {head_sample}\n"
  f"(Nota: Las filas completas han sido enviadas directamente como DataFrame a la interfaz... Genera un resumen breve de 1 o 2 líneas)."
  ```
* **Resultado:** Tiempos de respuesta de menos de 2 segundos, costo de tokens marginal y visualización interactiva de alta fidelidad con ordenamiento, filtrado y descarga.

---

### 3.2. Guardrails Multinivel con Parser AST (`sqlglot`)

#### ⚠️ La Falacia de Validar SQL con Expresiones Regulares (Regex)
Muchos proyectos intentan asegurar el SQL buscando palabras prohibidas con Regex: `re.search(r"DROP|DELETE", query)`. Esto es trivialmente evadible:
- Comentarios SQL: `/* comentario */ DROP TABLE usuarios;`
- Cadenas literales: `SELECT * FROM auditoria WHERE accion = 'DROP';` (falso positivo).
- Encodings raros o saltos de línea combinados con sentencias compuestas.

#### 💡 Nuestra Solución con `sqlglot`
Utilizamos [`sqlglot`](file:///c:/proyectos/tp2-ia-utn/db_copilot/sql_guard.py#L19-L144), un transpilador y analizador sintáctico formal de SQL que construye el **Árbol de Sintaxis Abstracta (AST)** según el dialecto configurado (`postgres` o `sqlite`):

```mermaid
graph TD
    RawSQL["SQL Generado por LLM"] --> AST[sqlglot.parse AST]
    AST --> CountCheck{"¿len(expressions) == 1?"}
    CountCheck -->|No: Múltiples sentencias| Block1["❌ BLOQUEO: Ataque de inyección encadenada (; DROP)"]
    CountCheck -->|Sí: Exactamente una| TypeCheck{"Tipo de Nodo AST"}
    
    TypeCheck -->|exp.Select| LimitCheck{"¿Tiene cláusula LIMIT?"}
    LimitCheck -->|No| InjectLimit["Inyectar ast.limit(500) en el AST"]
    LimitCheck -->|Sí| KeepLimit["Mantener LIMIT original"]
    InjectLimit --> AllowSelect["✅ SELECT Sanitizado -> Ejecutar"]
    KeepLimit --> AllowSelect
    
    TypeCheck -->|exp.Update / exp.Delete| WhereCheck{"¿Tiene cláusula WHERE?"}
    WhereCheck -->|No| WarnWhere["⚠️ Advertencia: Afecta toda la tabla"]
    WhereCheck -->|Sí| OKWhere["WHERE validado"]
    WarnWhere --> EnqueueWrite["🛑 Retener en Cola Human-in-the-Loop"]
    OKWhere --> EnqueueWrite
    
    TypeCheck -->|exp.Drop / exp.Alter / exp.Create / exp.Truncate| BlockDDL["❌ BLOQUEO ESTRICTO: Sentencia DDL Prohibida"]
```

1. **Anti-Inyección Encadenada:** `len(expressions) > 1` detiene inmediatamente ataques de escape clásico como `' UNION SELECT 1; DROP TABLE orders; --`.
2. **Inyección de Límite Defensivo:** Si el usuario pide *"dame las órdenes"*, el AST intercepta el nodo `Select` y si `ast.args.get("limit") is None`, muta el árbol inyectando `LIMIT 500`. La base de datos nunca sufrirá desbordamientos de memoria (*OOM*).
3. **Inmutabilidad Estricta de Esquema:** Cualquier intento de `DROP`, `ALTER`, `CREATE`, `TRUNCATE` o comandos de administración queda terminantemente bloqueado y registrado en el log de auditoría.

---

### 3.3. Human-in-the-Loop (HITL) para Operaciones de Modificación

#### ⚠️ El Peligro de Agentes Autónomos con Acceso de Escritura
Permitir que un agente ejecute `UPDATE` o `DELETE` automáticamente en producción es un riesgo inaceptable. Incluso con un 99% de precisión, el 1% de error puede significar borrar clientes o fijar precios a cero.

#### 💡 Nuestra Implementación de HITL
En [`agent.py`](file:///c:/proyectos/tp2-ia-utn/db_copilot/agent.py#L130-L248):
1. Cuando la validación detecta un `UPDATE` o `DELETE`, la herramienta `run_write` **nunca ejecuta la sentencia contra la base**.
2. Genera un identificador único (UUID de 8 caracteres, ej. `a3f91b2c`).
3. Congela la solicitud en un diccionario en memoria `_pending_writes` con estado `PENDING`.
4. La interfaz de Streamlit detecta solicitudes pendientes y dibuja una tarjeta de alerta con el SQL formateado, las advertencias (ej. si carece de `WHERE`) y dos botones:
   - **`✅ Aprobar`**: Invoca `approve_pending_write(id, approve=True, operator="Operador Humano")`, que abre una transacción atómica `with engine.begin(): conn.execute(...)`, registra las filas afectadas (`rowcount`) y marca el estado como `EXECUTED`.
   - **`❌ Rechazar`**: Marca el estado como `REJECTED`, cancela la ejecución y deja constancia en la auditoría.
5. **Auditoría Integral (*Audit Log*):** Cada intento (exitoso, pendiente, aprobado, rechazado o bloqueado) se persiste cronológicamente con marca de tiempo ISO-8601, clasificación, usuario u operador y motivo.

---

### 3.4. Bucle de Auto-Corrección Reflexiva (*Self-Healing SQL Loop*)

#### ⚠️ El Escenario de Falla Habitual
Incluso con RAG, un LLM puede equivocarse sutilmente en una cláusula de agregación:
* Intentar agrupar por `customers.first_name` olvidando incluir `customers.last_name` en el `GROUP BY` de PostgreSQL (que exige que todas las columnas proyectadas estén en el GROUP BY).
* Usar un alias que colisiona o una función no compatible con el dialecto específico.

En sistemas tradicionales, la aplicación arroja un error feo en pantalla (`Internal Server Error 500`) y la experiencia del usuario se arruina.

#### 💡 Nuestra Auto-Corrección en Dos Fases
En [`execute_copilot_step_by_step`](file:///c:/proyectos/tp2-ia-utn/db_copilot/agent.py#L448-L526):
1. Se atrapa la excepción de base de datos (`except Exception as exc: db_error = str(exc)`).
2. Se registra la fase en el timeline de observabilidad: `Detección de Error en Base de Datos`.
3. Se formula inmediatamente un prompt reflexivo de auto-corrección que contiene:
   - El SQL que falló.
   - El mensaje de error exacto retornado por el motor relacional.
   - El catálogo RAG con las columnas y relaciones reales.
4. El LLM razona la corrección, re-emite el SQL, este vuelve a pasar por `sqlglot` y se re-ejecuta.
5. Si la re-ejecución es exitosa, el usuario recibe sus datos acompañados de una nota técnica explicando qué ajuste se realizó de forma automática.

```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant Agente as DB Copilot
    participant LLM as Motor LLM
    participant Guard as sqlglot Guardrails
    participant DB as PostgreSQL / SQLite

    Usuario->>Agente: "Total gastado por cliente"
    Agente->>LLM: Prompt con RAG Schema
    LLM-->>Agente: SELECT c.name, SUM(o.total_amount)...
    Agente->>Guard: Validar AST
    Guard-->>Agente: Válido (SELECT)
    Agente->>DB: Ejecutar SQL
    DB-->>Agente: ❌ ERROR: column c.name does not exist
    Note over Agente: Activación de Bucle Reflexivo (Self-Healing)
    Agente->>LLM: Fix Prompt: Falló c.name. El esquema tiene first_name y last_name. Corrige el GROUP BY.
    LLM-->>Agente: SELECT c.first_name, c.last_name, SUM(o.total_amount)... GROUP BY c.first_name, c.last_name
    Agente->>Guard: Validar AST Corregido
    Guard-->>Agente: Válido (SELECT)
    Agente->>DB: Re-ejecutar SQL
    DB-->>Agente: ✅ Retorna 50 filas
    Agente-->>Usuario: DataFrame + Explicación de la auto-corrección
```

---

### 3.5. Resiliencia, Fallbacks Locales y Multi-Proveedor de LLM/Embeddings

El proyecto fue diseñado para ser **agnóstico al entorno**, permitiendo una defensa académica impecable sin depender de conexiones a internet inestables o cuotas de tarjetas de crédito:

1. **Soporte Híbrido OpenAI y Gemini:**
   - En [`config.py`](file:///c:/proyectos/tp2-ia-utn/db_copilot/config.py#L44-L103), la fábrica `get_llm()` detecta automáticamente las credenciales provistas (`OPENAI_API_KEY` o `GOOGLE_API_KEY`).
   - Soporte para **captura de pensamientos (*Thinking Process*)** en modelos que lo admiten (como Gemini 3.5 Flash o Gemini 3.6 Flash).
2. **Fallback Determinístico Local para Embeddings:**
   - Si no se cuenta con saldo o conectividad hacia la API de embeddings de OpenAI (`text-embedding-3-small`), la función [`get_embeddings()`](file:///c:/proyectos/tp2-ia-utn/db_copilot/config.py#L104-L142) instancia una clase propia `LocalHashEmbeddings` basada en el `HashingVectorizer` de Scikit-Learn (1024 características, normalización L2).
   - **Beneficio:** ChromaDB funciona al 100% de manera determinística, en milisegundos, sin consumir un solo centavo de cuota y sin riesgo de error HTTP 429.
3. **Degradación Elegante ante Saturación de API:**
   - Si una llamada al modelo principal devuelve errores de cuota (`429 RESOURCE_EXHAUSTED` o `503 UNAVAILABLE`), el orquestador conmuta automáticamente a un modelo ultraliviano de alta tasa (`gemini-3.5-flash-lite`), completando la tarea sin interrumpir al usuario.

---

### 3.6. DBML Dinámico y Renderizado Vectorial SVG

Para satisfacer el requerimiento de análisis visual del modelo de datos:
1. En [`schema_introspection.py`](file:///c:/proyectos/tp2-ia-utn/db_copilot/schema_introspection.py#L275-L339), la función `generate_dbml()` traduce la metadata de tablas, tipos de datos canónicos, claves primarias e interrelaciones foráneas al estándar **DBML (Database Markup Language)**.
2. A través de [`render_dbml.js`](file:///c:/proyectos/tp2-ia-utn/render_dbml.js), se ejecuta un proceso en Node.js que aprovecha el paquete oficial `@softwaretechnik/dbml-renderer` para generar un archivo SVG nítido y vectorial.
3. En la pestaña **Diagrama Entidad-Relación (DBML)** de la aplicación, el usuario puede inspeccionar el diagrama con zoom, copiar el código fuente DBML para usar en [dbdiagram.io](https://dbdiagram.io) o descargar tanto el `.dbml` como el `.svg`.

---

## 4. Desglose Módulo por Módulo

A continuación se detalla la responsabilidad de cada archivo que compone el paquete [`db_copilot`](file:///c:/proyectos/tp2-ia-utn/db_copilot):

```
db_copilot/
├── __init__.py                 # Marca de paquete y metadatos del TP2
├── config.py                   # Conexión SQLAlchemy, variables .env y fábricas de IA
├── schema_introspection.py     # Extracción de metadatos, traducción a NLP y DBML
├── rag.py                      # Vector Store (Chroma), chunking y Retriever del esquema
├── sql_guard.py                # Guardrails formales con sqlglot (AST, LIMIT, Seguridad)
├── agent.py                    # Agente SQL observable, herramientas @tool, HITL y audit trail
├── app.py                      # Frontend Streamlit (Chat interactivo, pestañas y profiler)
├── seed_enterprise.py          # DDL complejo de 15 tablas y sembrado masivo Faker
└── seed_data.py                # Sembrado alternativo ligero de 4 tablas para pruebas rápidas
```

### `config.py`
- Normaliza los strings de conexión: convierte `postgresql://` a `postgresql+psycopg2://` de forma transparente.
- Define `DEFAULT_POSTGRES_URL` (para el servidor PostgreSQL local de desarrollo) y `SQLITE_FALLBACK_URL` (para una base local autocontenida en `data/ecommerce.db`).
- Expone `get_engine()`, `get_llm()` y `get_embeddings()`.

### `schema_introspection.py`
- `introspect_database(engine)`: Utiliza `sqlalchemy.inspect(engine)` para consultar el catálogo de PostgreSQL/SQLite en vivo. Extrae: nombres de tablas, tipos de columnas, nulos, valores por defecto, claves primarias, claves foráneas, índices creados y conteo estimado de filas.
- `parse_ddl_schema(ddl_sql)` y `parse_json_schema(json_data)`: Permiten operar en modo desconectado a partir de scripts `.sql` o especificaciones JSON.
- `generate_natural_language_docs(schema_meta)`: Transforma la metadata estructurada en prosa en lenguaje natural. Agrega un diccionario semántico de sinónimos en español para que el retriever entienda que *"clientes"* se refiere a `customers` (y recuerda que se compone de `first_name` y `last_name`), que *"despacho"* se refiere a `shipments`, etc.
- `generate_dbml(schema_meta)` y `render_dbml_to_svg(dbml_str)`: Convierten el esquema al estándar DBML y orquestan la generación de gráficos vectoriales SVG con Node.js.

### `rag.py`
- Configura ChromaDB con persistencia en `data/chroma_db`.
- `index_schema_documents(docs)`: Aplica `RecursiveCharacterTextSplitter` (chunk de 700 caracteres, overlap de 80) e indexa los documentos categorizados por metadata (`tipo: tabla | relacion | motor | indice`).
- `retrieve_schema_context(query, k)`: Retriever inteligente que balancea resultados para asegurar que el prompt reciba tanto la definición de las tablas involucradas como las relaciones foráneas (FKs) que permiten hacer los `JOIN`.
- `answer_schema_question(query)`: Implementa el **Modo Documentación (RAG Puro)**, combinando un prompt contextual con el LLM mediante LCEL (`ChatPromptTemplate | llm | StrOutputParser()`), respondiendo consultas conceptuales sin tocar la base.

### `sql_guard.py`
- `validate_and_classify_sql(sql_text, default_limit=500, dialect="postgres")`:
  - Parsea el SQL con `sqlglot.parse(cleaned_sql, read=dialect)`.
  - Si `len(expressions) > 1`: rechaza con clasificación `FORBIDDEN` (previene inyecciones múltiples).
  - Si es `exp.Select`: inyecta cláusula `LIMIT 500` si estaba ausente y retorna `SELECT`.
  - Si es `exp.Update` o `exp.Delete`: detecta presencia o ausencia de cláusula `WHERE` y clasifica como `WRITE`.
  - Si es `exp.Drop`, `exp.Alter`, `exp.Create`, `exp.Truncate` o similares: clasifica como `FORBIDDEN` y bloquea la operación.

### `agent.py`
- Registra el estado de sesión: `_context_store`, `_pending_writes` y `_audit_log`.
- Define las herramientas decoradas con `@tool`:
  - `retrieve_schema(query)`: Obliga al agente a anclarse en el catálogo real.
  - `run_select(sql)`: Valida con guardrail, ejecuta contra la base, guarda el DataFrame y devuelve un resumen conciso de 1-2 líneas al LLM.
  - `run_write(sql)`: Valida con guardrail y retiene en la cola de aprobación.
- `execute_copilot_step_by_step(...)`: Motor de ejecución observable dividido en 5 fases con medición milimétrica de tiempos, captura de *thinking* y bucle de auto-corrección.
- Clase `DBCopilot`: Fachada que expone el método unificado `copilot.ask(question, mode="schema"|"agent", on_step_callback=...)`.

### `app.py`
- Interfaz gráfica en Streamlit con diseño responsive de nivel empresarial:
  - **Sidebar:** Estado de conexión, configuración activa de motor y modelo LLM, botón para tumbar y recrear la base completa, y cargador de esquemas externos.
  - **Banner Superior:** Bandeja de aprobaciones pendientes Human-in-the-Loop.
  - **Pestaña 1 (Chat Inteligente):** Radio button interactivo para cambiar entre Modo Agente y Modo RAG, historial con SQL ejecutado en código formateado, DataFrames embebidos con descarga CSV, expander de pensamiento del modelo (*Thinking*) y desglose temporal de fases.
  - **Pestaña 2 (Carga & Gestión de Esquema SQL):** Carga de esquemas predefinidos (15 tablas o 4 tablas) o subida de `.sql` propio, con visor de código y sincronización en 1 clic.
  - **Pestaña 3 (Diagrama ER DBML):** Visualizador de SVG interactivo y descargador de DBML.
  - **Pestaña 4 (Script DDL & Explorador de Tablas):** Visor del DDL completo y visor de datos en vivo que permite seleccionar cualquier tabla, ver sus columnas, tipos y una muestra real de los primeros 10 registros.
  - **Pestaña 5 (Audit Log):** Tabla histórica completa con auditoría de cada acción.

### `seed_enterprise.py` & `seed_data.py`
- `seed_enterprise.py`: Implementa `drop_and_recreate_schema()` que ejecuta `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` en PostgreSQL, crea las 15 tablas con tipos estrictos, claves foráneas e índices, y puebla más de 150 órdenes con productos, empleados, almacenes, clientes, pagos, despachos y reseñas consistentes generadas mediante `Faker("es_ES")`.

---

## 5. Modelo de Datos Empresarial (15 Tablas Relacionadas)

Para demostrar la capacidad del agente en un entorno realista de alta complejidad, se diseñó un modelo relacional de **15 tablas** que modela una compañía de comercio electrónico omnicanal y distribución logística:

```mermaid
erDiagram
    departments ||--o{ employees : "asigna personal"
    employees ||--o{ orders : "gestiona ventas"
    warehouses ||--o{ inventory : "almacena stock"
    warehouses ||--o{ orders : "despacha desde"
    suppliers ||--o{ products : "suministra"
    categories ||--o{ categories : "subcategorías (auto-ref)"
    categories ||--o{ products : "clasifica"
    products ||--o{ inventory : "registra existencias"
    products ||--o{ order_items : "se incluye en"
    products ||--o{ product_reviews : "recibe calificaciones"
    customers ||--o{ customer_addresses : "posee domicilios"
    customers ||--o{ orders : "realiza compras"
    customers ||--o{ product_reviews : "redacta reseñas"
    promotions ||--o{ orders : "aplica descuento a"
    orders ||--o{ order_items : "contiene líneas"
    orders ||--o{ payments : "registra cobros"
    orders ||--o{ shipments : "origina envíos"
    customer_addresses ||--o{ shipments : "destino de entrega"

    departments {
        int id PK
        varchar name
        varchar code
        numeric budget
    }
    employees {
        int id PK
        int department_id FK
        varchar first_name
        varchar last_name
        varchar email
        numeric salary
    }
    warehouses {
        int id PK
        varchar name
        varchar city
        int capacity_sqm
    }
    suppliers {
        int id PK
        varchar company_name
        numeric rating
    }
    categories {
        int id PK
        int parent_id FK
        varchar name
        varchar slug
    }
    products {
        int id PK
        int category_id FK
        int supplier_id FK
        varchar sku
        varchar name
        numeric cost_price
        numeric sale_price
    }
    inventory {
        int id PK
        int warehouse_id FK
        int product_id FK
        int quantity
        int min_threshold
    }
    customers {
        int id PK
        varchar account_type
        varchar first_name
        varchar last_name
        varchar email
        numeric credit_limit
    }
    customer_addresses {
        int id PK
        int customer_id FK
        varchar street
        varchar city
    }
    promotions {
        int id PK
        varchar code
        numeric discount_pct
    }
    orders {
        int id PK
        int customer_id FK
        int assigned_employee_id FK
        int warehouse_id FK
        int promotion_id FK
        varchar order_number
        varchar status
        numeric total_amount
    }
    order_items {
        int id PK
        int order_id FK
        int product_id FK
        int quantity
        numeric unit_price
        numeric line_total
    }
    payments {
        int id PK
        int order_id FK
        varchar payment_method
        numeric amount
        varchar status
    }
    shipments {
        int id PK
        int order_id FK
        varchar carrier
        varchar tracking_code
        varchar status
    }
    product_reviews {
        int id PK
        int product_id FK
        int customer_id FK
        int rating
        text comment
    }
```

### Particularidades Arquitectónicas del Modelo:
1. **Relación Jerárquica Auto-referencial:** `categories.parent_id` referencia a `categories.id`, permitiendo árboles de navegación (ej. *Electrónica > Computación > Notebooks*).
2. **Relación Muchos a Muchos (N-M) con Atributos Propios:** `inventory` une `warehouses` y `products`, almacenando `quantity`, `min_threshold` y fecha de reposición con una restricción `UNIQUE(warehouse_id, product_id)`.
3. **Múltiples Claves Foráneas en una Misma Entidad:** La tabla `orders` converge 4 relaciones: hacia `customers`, `employees`, `warehouses` y `promotions`.
4. **Índices Estratégicos:** Se definieron índices B-Tree en columnas de filtrado frecuente (`idx_orders_date`, `idx_orders_status`, `idx_products_category`, etc.) que son documentados e indexados en el RAG para que el agente aprenda a optimizar sus consultas.

---

## 6. Flujos de Ejecución Detallados (Paso a Paso con Diagramas de Secuencia)

### Caso A: Consulta de Documentación y Arquitectura (RAG Puro)
* **Pregunta del usuario:** *"¿Cómo se relaciona la tabla order_items con products e inventory?"*
* **Flujo:**
  1. El usuario selecciona **Modo Documentación / Esquema (RAG)** en la interfaz.
  2. `copilot.ask(question, mode="schema")` saltea toda conexión a la base relacional.
  3. `retrieve_schema_context()` realiza una búsqueda de similitud de coseno en ChromaDB, extrayendo las definiciones de las 3 tablas y sus foreign keys.
  4. La cadena LCEL combina el contexto con el prompt de síntesis conceptual.
  5. El LLM responde explicando las claves foráneas y la cardinalidad de muchos a uno.
  6. **Tiempo total:** ~0.8s a 1.5s. Cero consultas SQL enviadas al motor.

---

### Caso B: Consulta Operacional de Lectura (`SELECT`)
* **Pregunta del usuario:** *"Mostrame los 5 clientes que más dinero gastaron en total"*
* **Flujo:**
  1. El agente recupera el esquema relevante de `customers` y `orders` desde Chroma.
  2. El LLM elabora la consulta SQL calculando el agregado:
     ```sql
     SELECT c.first_name, c.last_name, SUM(o.total_amount) AS total_gastado
     FROM customers c
     JOIN orders o ON c.id = o.customer_id
     GROUP BY c.first_name, c.last_name
     ORDER BY total_gastado DESC
     LIMIT 5
     ```
  3. `validate_and_classify_sql` analiza el AST en `sqlglot`:
     - Verifica sentencia única: OK.
     - Clasifica como `SELECT`: OK.
     - Confirma presencia de `LIMIT`: OK.
  4. Se ejecuta en PostgreSQL mediante SQLAlchemy y se carga en `pandas.DataFrame`.
  5. Se almacena el DataFrame para la UI y se envía solo el resumen (5 filas, nombres de columnas) al LLM.
  6. El LLM emite: *"Se encontraron los 5 clientes con mayor volumen de compra acumulado, liderados por..."*.
  7. La UI renderiza la tabla interactiva y activa el botón de descarga CSV.

---

### Caso C: Consulta con Error de Columna y Auto-Corrección
* **Pregunta del usuario:** *"Listar el nombre y email de todos los clientes activos"*
* **Flujo:**
  1. El LLM genera inicialmente: `SELECT name, email FROM customers WHERE is_active = TRUE;`.
  2. Pasa los guardrails de `sqlglot` (sintácticamente es un SELECT válido).
  3. Al ejecutarse en PostgreSQL, la base rechaza: `column "name" does not exist`.
  4. La función `execute_copilot_step_by_step` atrapa el error y activa la fase de auto-corrección.
  5. Se envía un prompt de corrección reflexiva al LLM con el error del motor y el catálogo real.
  6. El LLM detecta que debe usar `first_name` y `last_name`:
     ```sql
     SELECT first_name, last_name, email FROM customers WHERE is_active = TRUE LIMIT 500;
     ```
  7. Se re-valida y re-ejecuta exitosamente.
  8. El usuario recibe los datos sin haber experimentado una caída de la aplicación.

---

### Caso D: Solicitud de Escritura (`UPDATE`/`DELETE`) y Aprobación Humana
* **Pregunta del usuario:** *"Actualizá el estado de la orden ORD-1002 a delivered"*
* **Flujo:**
  1. El LLM genera: `UPDATE orders SET status = 'delivered' WHERE order_number = 'ORD-1002';`.
  2. `sqlglot` clasifica el AST como `WRITE` y verifica la cláusula `WHERE`.
  3. `run_write` genera el ID de acción `b7a19c4d`, encola la solicitud como `PENDING` y no toca la base.
  4. En la interfaz de Streamlit aparece la alerta roja de aprobación con el código SQL y la advertencia.
  5. El operador revisa la sentencia y hace clic en `✅ Aprobar`.
  6. `approve_pending_write` abre una transacción atómica y ejecuta el cambio.
  7. El log de auditoría se actualiza: `APPROVED_AND_EXECUTED | Filas afectadas: 1 | Operador: Operador Streamlit`.

---

### Caso E: Detección y Bloqueo de Sentencias Prohibidas o Maliciosas
* **Intento malicioso o prompt injection:** *"Borrá la tabla de productos para empezar de cero"*
* **Flujo:**
  1. El LLM propone: `DROP TABLE products;`.
  2. `sqlglot` parsea el AST y detecta el nodo `exp.Drop`.
  3. El guardrail bloquea de inmediato la operación:
     `Operación 'DROP' no permitida. Las operaciones DDL están estrictamente bloqueadas.`
  4. Se aborta la ejecución antes de tocar la base de datos.
  5. Se registra en `_audit_log` con estado `BLOCKED` y motivo de seguridad.
  6. El usuario recibe el mensaje de bloqueo preventivo.

---

## 7. Observabilidad, Profiling y Métricas en Tiempo Real

Para maximizar la transparencia ante auditorías y defensas técnicas, el sistema incorpora un **Profiler Temporal Fase por Fase**:

| Fase | Entorno / Target | Qué Mide |
| :--- | :--- | :--- |
| **1. Recuperación RAG de Esquema** | Local (ChromaDB) | Latencia de búsqueda semántica y recuperación de chunks de tablas y relaciones (~0.05s). |
| **2. Generación SQL y Razonamiento** | API Cloud (Gemini / OpenAI) | Tiempo de inferencia del LLM y generación del candidato SQL (~1.2s - 2.5s). |
| **3. Validación de Guardrails** | Local (sqlglot AST) | Análisis sintáctico, detección de inyección e inyección de LIMIT (~0.01s). |
| **4. Ejecución en Base de Datos** | Servidor PostgreSQL / SQLite | Tiempo de red y ejecución de la consulta relacional en el motor (~0.02s - 0.08s). |
| **5. Auto-corrección (si aplica)** | Cloud + Local | Tiempo insumido por el reintento reflexivo en caso de error. |

Adicionalmente, cuando se utilizan modelos con soporte de razonamiento, la interfaz extrae y muestra el **Thinking Process** (la cadena de deducción interna del LLM previa a emitir el SQL), lo que permite inspeccionar por qué eligió ciertos filtros o uniones.

---

## 8. Guía de Instalación, Configuración y Despliegue

### Requisitos Previos
* Python 3.10 o superior (compatible con Python 3.11, 3.12 y 3.13).
* PostgreSQL 14+ (opcional; si no está instalado, el sistema funciona de forma autónoma con SQLite local).
* Node.js v16+ (opcional, únicamente necesario para renderizar el diagrama DBML a SVG localmente).

### Paso 1: Clonar y Crear Entorno Virtual
```bash
git clone <url-del-repositorio>
cd tp2-ia-utn

python -m venv .venv
# En Windows:
.venv\Scripts\activate
# En Linux/Mac:
source .venv/bin/activate
```

### Paso 2: Instalar Dependencias
```bash
pip install -r requirements.txt
```

Si deseas la generación local de diagramas SVG:
```bash
npm install @softwaretechnik/dbml-renderer
```

### Paso 3: Configurar Variables de Entorno (`.env`)
Crear un archivo `.env` en la raíz del proyecto basándose en `.env.example`:

```env
# Proveedor de Inteligencia Artificial (GEMINI u OPENAI)
LLM_PROVIDER=GEMINI
GOOGLE_API_KEY=tu_api_key_de_gemini_aqui
GEMINI_MODEL=gemini-3.5-flash-lite

# O si utilizas OpenAI:
# LLM_PROVIDER=OPENAI
# OPENAI_API_KEY=tu_api_key_de_openai_aqui
# OPENAI_MODEL=gpt-4o-mini

# Cadena de conexión a Base de Datos:
# Opción A: PostgreSQL
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/ecommerce_db

# Opción B: SQLite local portable (si no tienes PostgreSQL levantado)
# DATABASE_URL=sqlite:///data/ecommerce.db
```

### Paso 4: Ejecutar la Aplicación Interactiva
```bash
streamlit run db_copilot/app.py
```
La aplicación se abrirá en `http://localhost:8501`.

### Paso 5: Ejecutar el Notebook de Demostración
Para la corrección académica guiada:
```bash
jupyter notebook notebooks/demo.ipynb
```

---

## 9. Defensa Oral del Proyecto (Tips & Preguntas Frecuentes de Examen)

Al presentar este trabajo práctico ante una mesa evaluadora de Sistemas Inteligentes de la UTN, se recomienda poner el foco en las decisiones arquitectónicas que diferencian este desarrollo de un simple script de prueba:

### 1. ¿Por qué usar RAG sobre el esquema y no inyectar todo el DDL en el System Prompt?
> *"En bases de datos de juguete con 2 o 3 tablas, pasar todo el `CREATE TABLE` en el prompt es factible. En entornos empresariales con 15 o más tablas y cientos de columnas, inyectar todo el esquema en cada petición satura la ventana de contexto, aumenta el costo exponencialmente e incrementa la probabilidad de que el modelo confunda columnas de tablas no relacionadas. RAG permite recuperar selectivamente solo las tablas, relaciones e índices pertinentes para la consulta puntual del usuario."*

### 2. ¿Por qué se utilizó `sqlglot` para los guardrails en lugar de expresiones regulares?
> *"Las expresiones regulares operan a nivel de texto plano y no entienden la estructura sintáctica de un lenguaje de programación. Es sumamente fácil vulnerar un regex mediante saltos de línea, comentarios SQL (`/* ... */`), o subconsultas. `sqlglot` genera un Árbol de Sintaxis Abstracta (AST) formal respetando la gramática del dialecto de destino (PostgreSQL), permitiendo inspeccionar el tipo de nodo (`Select`, `Update`, `Drop`), garantizar que haya una única sentencia e inyectar cláusulas `LIMIT` directamente en el árbol sintáctico."*

### 3. ¿Cómo resolvieron el problema de devolver miles de filas sin agotar la memoria del LLM?
> *"Implementamos una separación estricta entre el canal de datos y el canal conversacional. La herramienta `run_select` deposita el `pandas.DataFrame` resultante en la capa de presentación visual (Streamlit), mientras que al LLM únicamente se le envía una síntesis técnica de 2 líneas (cantidad de filas, nombres de columnas y muestra de 2 registros). Esto mantiene las respuestas en menos de 2 segundos y con un costo de tokens mínimo."*

### 4. ¿Qué ocurre si el usuario pide una modificación destructiva (`DROP TABLE` o `DELETE`)?
> *"Las sentencias DDL como `DROP`, `ALTER` o `TRUNCATE` son bloqueadas de forma tajante en la capa de guardrails y registradas en el Audit Log como incidentes de seguridad. Las operaciones de mutación válidas (`UPDATE` y `DELETE`) se suspenden mediante un patrón Human-In-The-Loop: se retienen en una cola con un identificador único en estado `PENDING` y solo impactan en la base si un operador humano las aprueba explícitamente desde la interfaz."*

### 5. ¿Cómo garantizan que el sistema no se caiga ante fallos de conexión o cuota de API?
> *"El sistema implementa una política de fallbacks en múltiples niveles: en embeddings, si falla la API cloud, conmuta a un vectorizador local determinístico `LocalHashEmbeddings` con Scikit-Learn; en base de datos, si PostgreSQL no está disponible, conmuta a una réplica portable en SQLite; y en LLMs, si ocurre saturación de cuota HTTP 429, redirige automáticamente a modelos livianos de respaldo."*

---

*Documento técnico compilado para la cátedra de Sistemas Inteligentes — UTN.*
