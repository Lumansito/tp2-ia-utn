import base64
import json
import urllib.request
from pathlib import Path

diagrams = {
    "paso_1_retrieve_schema": """sequenceDiagram
    autonumber
    actor User as Operario (UI)
    participant LG as LangGraph
    participant Gem as Google Gemini API (LLM)
    participant RAG as ChromaDB

    User->>LG: "¿Cuáles son los 3 productos más caros?"
    Note over LG: Inicia el agente ReAct.<br/>Estado: [SystemPrompt, HumanMessage]
    LG->>Gem: Envía historial + definición de 5 Tools
    Gem-->>LG: tool_call: retrieve_schema(query="productos precio")
    LG->>RAG: Búsqueda por similitud semántica
    RAG-->>LG: "[TABLA: Producto] columnas: id, nombre, precioVenta..."
    Note over LG: Agrega ToolMessage al contexto
""",

    "paso_2_run_select_fallo": """sequenceDiagram
    autonumber
    participant LG as LangGraph
    participant Gem as Google Gemini API (LLM)
    participant Guard as SQL Guardrails (sqlglot)
    participant DB as PostgreSQL DB

    Note over LG: Estado actual: Historial + Contexto RAG
    LG->>Gem: Envía mensajes acumulados
    Gem-->>LG: tool_call: run_select(sql="SELECT nombre, precioVenta FROM Producto ORDER BY precioVenta DESC LIMIT 3")
    LG->>Guard: Valida sintaxis y cláusulas
    Guard-->>LG: SQL Válido (Solo lectura)
    LG->>DB: Ejecuta consulta en PostgreSQL
    DB-->>LG: ERROR: (psycopg2.errors.UndefinedTable) relation "producto" does not exist
    Note over LG: Captura error y agrega ToolMessage al contexto
""",

    "paso_3_list_tables_autocorreccion": """sequenceDiagram
    autonumber
    participant LG as LangGraph
    participant Gem as Google Gemini API (LLM)

    Note over LG: Estado actual: Historial + Error de PostgreSQL
    LG->>Gem: Envía mensajes (Gemini detecta error de tabla)
    Gem-->>LG: tool_call: list_tables()
    Note over LG: Consulta metadata en memoria (SQLAlchemy)
    LG-->>LG: Tablas disponibles: Producto, Usuario, Sucursal, Categoria...
    Note over LG: Agrega ToolMessage con nombres reales de tablas
""",

    "paso_4_describe_table": """sequenceDiagram
    autonumber
    participant LG as LangGraph
    participant Gem as Google Gemini API (LLM)

    Note over LG: Estado actual: Historial + Nombres confirmados
    LG->>Gem: Envía mensajes acumulados
    Gem-->>LG: tool_call: describe_table(table_name="Producto")
    Note over LG: Extrae columnas y tipos reales de 'Producto'
    LG-->>LG: Columnas: id (INT), nombre (TEXT), precioVenta (NUMERIC)...
    Note over LG: Agrega ToolMessage con detalle de columnas
""",

    "paso_5_run_select_exito": """sequenceDiagram
    autonumber
    participant LG as LangGraph
    participant Gem as Google Gemini API (LLM)
    participant Guard as SQL Guardrails (sqlglot)
    participant DB as PostgreSQL DB

    Note over LG: Estado actual: Columnas y casing exactos verificados
    LG->>Gem: Envía mensajes acumulados
    Gem-->>LG: tool_call: run_select(sql="SELECT nombre, \"precioVenta\" FROM \"Producto\" ORDER BY \"precioVenta\" DESC LIMIT 3")
    LG->>Guard: Valida SQL (Asegura LIMIT)
    Guard-->>LG: SQL Seguro
    LG->>DB: Ejecuta en PostgreSQL
    DB-->>LG: 3 filas obtenidas (UPS GALAXY VX 1500kVA, etc.)
    Note over LG: Guarda DataFrame en sesión y agrega ToolMessage
""",

    "paso_6_respuesta_final": """sequenceDiagram
    autonumber
    actor User as Operario (UI)
    participant LG as LangGraph
    participant Gem as Google Gemini API (LLM)

    Note over LG: Estado actual: Datos obtenidos con éxito
    LG->>Gem: Envía historial completo con resultados de BD
    Gem-->>LG: Respuesta final (Sin llamadas a tools)
    LG-->>User: "Los 3 productos más caros son: 1) UPS GALAXY VX ($59.614.715)..."
    Note over User: Visualiza respuesta en lenguaje natural + DataFrame interactivo
"""
}

out_dir = Path(r"c:\proyectos\tp2-ia-utn\docs\diagramas_svg")
out_dir.mkdir(parents=True, exist_ok=True)

for name, mmd in diagrams.items():
    state_obj = {
        "code": mmd,
        "mermaid": {"theme": "default"}
    }
    json_bytes = json.dumps(state_obj).encode("utf-8")
    b64_str = base64.b64encode(json_bytes).decode("ascii")
    url = f"https://mermaid.ink/svg/{b64_str}"
    print(f"Descargando SVG para {name}...")
    
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        svg_content = resp.read().decode("utf-8")
        
    out_file = out_dir / f"{name}.svg"
    out_file.write_text(svg_content, encoding="utf-8")
    print(f"Guardado: {out_file}")

print("Todos los SVGs fueron generados exitosamente!")
