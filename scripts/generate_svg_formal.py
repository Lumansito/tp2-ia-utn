import base64
import json
import urllib.request
from pathlib import Path

# Configuración de tema formal/sobrio (Base blanca, líneas grises/negras, sin arcoíris)
# Participantes fijos en TODOS los diagramas para consistencia visual absoluta
PARTICIPANTS_HEADER = """
    autonumber
    actor User as Operario (UI)
    participant LG as LangGraph (Orquestador)
    participant Gem as Gemini API (LLM)
    participant RAG as ChromaDB (Vectores)
    participant Guard as SQL Guardrails (sqlglot)
    participant DB as PostgreSQL (Base de Datos)
"""

diagrams = {
    # 0. VISTA GENERAL (GROSO MODO)
    "00_resumen_global_6_pasos": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    User->>LG: Consulta en Lenguaje Natural
    Note over LG,Gem: Paso 1: Descubrimiento Semántico (RAG)
    LG->>Gem: Petición inicial + Tools
    Gem-->>LG: tool_call: retrieve_schema
    LG->>RAG: Búsqueda vectorial
    RAG-->>LG: Contexto relevante de tablas

    Note over LG,DB: Paso 2: Generación SQL y Detección de Error
    LG->>Gem: Envía contexto RAG
    Gem-->>LG: tool_call: run_select (SQL inicial)
    LG->>Guard: Valida SQL
    Guard-->>LG: Válido
    LG->>DB: Ejecuta consulta
    DB-->>LG: Error de tabla no encontrada

    Note over LG,Gem: Paso 3 & 4: Inspección y Auto-corrección
    LG->>Gem: Envía error de ejecución
    Gem-->>LG: tool_call: list_tables & describe_table
    LG-->>Gem: Metadata exacta y nombres reales

    Note over LG,DB: Paso 5: Reintento Exitoso
    Gem-->>LG: tool_call: run_select (SQL Corregido)
    LG->>Guard: Valida SQL
    Guard-->>LG: Válido
    LG->>DB: Ejecuta en PostgreSQL
    DB-->>LG: Datos recuperados (3 registros)

    Note over User,Gem: Paso 6: Respuesta Final
    LG->>Gem: Envía dataset obtenido
    Gem-->>LG: Explicación en lenguaje natural
    LG-->>User: Respuesta final + DataFrame en UI
""",

    # 1. PASO 1 DETALLE
    "01_paso_1_retrieve_schema": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    User->>LG: "¿Cuáles son los 3 productos más caros?"
    Note over LG: Inicializa estado del Grafo ReAct
    LG->>Gem: Envía System Prompt + Consulta + Definición de 5 Tools
    Gem-->>LG: tool_call: retrieve_schema(query="productos precio")
    LG->>RAG: Búsqueda por similitud semántica (Top-k)
    RAG-->>LG: Fragmento descriptivo: [TABLA: Producto] columnas, tipos, PK
    Note over LG: Actualiza Estado con ToolMessage de ChromaDB
""",

    # 2. PASO 2 DETALLE
    "02_paso_2_run_select_fallo": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    Note over LG: Estado: Consulta + Contexto RAG
    LG->>Gem: Envía mensajes acumulados
    Gem-->>LG: tool_call: run_select(sql="SELECT nombre, precioVenta FROM Producto ORDER BY precioVenta DESC LIMIT 3")
    LG->>Guard: Análisis AST y validación (Solo lectura)
    Guard-->>LG: Sentencia SELECT aprobada
    LG->>DB: Envía consulta a PostgreSQL
    DB-->>LG: Error: relation "producto" does not exist (UndefinedTable)
    Note over LG: Registra error en log de auditoría y lo agrega al Estado
""",

    # 3. PASO 3 DETALLE
    "03_paso_3_list_tables": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    Note over LG: Estado: Historial + Error de PostgreSQL
    LG->>Gem: Envía mensaje con el fallo retornado por la base
    Note over Gem: LLM analiza el error y decide listar tablas reales
    Gem-->>LG: tool_call: list_tables()
    Note over LG: Lee catálogo relacional en memoria (SQLAlchemy)
    LG-->>LG: Tablas disponibles: Producto, Usuario, Sucursal, Categoria...
    Note over LG: Agrega lista de tablas al Estado
""",

    # 4. PASO 4 DETALLE
    "04_paso_4_describe_table": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    Note over LG: Estado: Historial + Catálogo de tablas confirmado
    LG->>Gem: Envía lista de tablas verificadas
    Gem-->>LG: tool_call: describe_table(table_name="Producto")
    Note over LG: Extrae definición DDL y columnas exactas desde SQLAlchemy
    LG-->>LG: Columnas: id (INT), nombre (TEXT), precioVenta (NUMERIC)...
    Note over LG: Agrega esquema exacto al Estado
""",

    # 5. PASO 5 DETALLE
    "05_paso_5_run_select_exito": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    Note over LG: Estado: Nombres entrecomillados y columnas verificadas
    LG->>Gem: Envía esquema preciso de la tabla 'Producto'
    Gem-->>LG: tool_call: run_select(sql="SELECT nombre, \\"precioVenta\\" FROM \\"Producto\\" ORDER BY \\"precioVenta\\" DESC LIMIT 3")
    LG->>Guard: Valida AST e inyecta límites de seguridad
    Guard-->>LG: Sentencia aprobada
    LG->>DB: Ejecuta en PostgreSQL
    DB-->>LG: 3 registros devueltos con éxito
    Note over LG: Almacena DataFrame en contexto de sesión
""",

    # 6. PASO 6 DETALLE
    "06_paso_6_respuesta_final": f"""sequenceDiagram
{PARTICIPANTS_HEADER}
    Note over LG: Estado: Dataset completo en memoria
    LG->>Gem: Envía resumen de registros obtenidos
    Note over Gem: Genera síntesis final sin llamadas a herramientas
    Gem-->>LG: "Los 3 productos más caros son: 1) UPS GALAXY VX ($59.614.715)..."
    LG-->>User: Muestra respuesta final + Tabla interactiva de resultados
"""
}

out_dir = Path(r"c:\proyectos\tp2-ia-utn\docs\diagramas_svg")
out_dir.mkdir(parents=True, exist_ok=True)

for name, mmd in diagrams.items():
    state_obj = {
        "code": mmd,
        "mermaid": {
            "theme": "neutral",
            "sequence": {
                "showSequenceNumbers": True,
                "actorFontSize": 14,
                "messageFontSize": 13,
                "noteFontSize": 12
            }
        }
    }
    json_bytes = json.dumps(state_obj).encode("utf-8")
    b64_str = base64.b64encode(json_bytes).decode("ascii")
    url = f"https://mermaid.ink/svg/{b64_str}"
    print(f"Generando SVG formal para {name}...")
    
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        svg_content = resp.read().decode("utf-8")
        
    out_file = out_dir / f"{name}.svg"
    out_file.write_text(svg_content, encoding="utf-8")
    print(f"Guardado: {out_file}")

print("\nTodos los diagramas formales fueron generados con éxito!")
