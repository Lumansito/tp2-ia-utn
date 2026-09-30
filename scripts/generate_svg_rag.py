import base64
import json
import urllib.request
from pathlib import Path

# Participantes fijos en TODOS los diagramas de RAG
PARTICIPANTS_RAG_HEADER = """
    autonumber
    actor User as Operario (UI)
    participant App as Backend Python (DBCopilot)
    participant DB as PostgreSQL (Base de Datos)
    participant Emb as Gemini Embeddings API
    participant Chroma as ChromaDB (Vector Store)
    participant LLM as Gemini LLM API
"""

rag_diagrams = {
    # 0. RESUMEN GLOBAL RAG
    "rag_00_resumen_global": f"""sequenceDiagram
{PARTICIPANTS_RAG_HEADER}
    Note over App,DB: Fase A: Introspeccion e Indexacion (Arranque)
    App->>DB: Introspeccion de esquema via SQLAlchemy
    DB-->>App: Metadata tecnica estructurada
    Note over App: Genera documentos NLP y divide en Chunks
    App->>Emb: Envia chunks para vectorizar
    Emb-->>App: Vectores numericos (Embeddings)
    App->>Chroma: Almacena vectores con texto y metadatos

    Note over User,LLM: Fase B: Consulta del Operario (Modo Documentacion)
    User->>App: Consulta: Como se relacionan productos y proveedores?
    App->>Emb: Vectoriza consulta del usuario
    Emb-->>App: Vector de la consulta
    App->>Chroma: Busqueda por similitud semantica (Top-k)
    Chroma-->>App: Fragmentos de relaciones y tablas relevantes
    App->>LLM: Inyecta contexto recuperado + Prompt estricto
    LLM-->>App: Respuesta conceptual fundamentada
    App-->>User: Muestra explicacion detallada en UI
""",

    # 1. FETCH E INTROSPECCIÓN
    "rag_01_fetch_introspeccion": f"""sequenceDiagram
{PARTICIPANTS_RAG_HEADER}
    Note over App: Sincronizacion del catalogo
    App->>DB: inspect(engine) -> get_table_names, columns, foreign_keys
    Note over DB: Extrae metadatos: pg_class, constraints, comments
    DB-->>App: Diccionario de metadatos (Tablas, PK y FK, Tipos, Comentarios)
    Note over App: Calcula Fingerprint SHA-256 para evitar reindexar si no cambio
""",

    # 2. DOCUMENTOS NLP Y CHUNKING
    "rag_02_docs_nlp_y_chunking": f"""sequenceDiagram
{PARTICIPANTS_RAG_HEADER}
    Note over App: Transforma metadata en documentos de lenguaje natural
    Note over App: generate_natural_language_docs():<br/>1 Doc Motor<br/>N Docs de Tablas (con columnas y tipos)<br/>N Docs de Relaciones FK (origen y destino)<br/>N Docs de Indices
    Note over App: Aplica RecursiveCharacterTextSplitter (chunk_size=700, overlap=80)
    Note over App: Cada chunk conserva metadatos (tipo: relacion o tabla, nombre)
""",

    # 3. VECTORIZACIÓN Y GUARDADO CHROMADB
    "rag_03_vectorizacion_chromadb": f"""sequenceDiagram
{PARTICIPANTS_RAG_HEADER}
    Note over App: Chunks listos para indexar
    App->>Emb: Envia textos de los chunks a la API de Embeddings
    Note over Emb: Convierte fragmentos de texto en vectores de alta dimension
    Emb-->>App: Vectores numericos (embeddings)
    App->>Chroma: Guarda documentos con vectores en coleccion db_schema_docs
    Note over Chroma: Persiste indice vectorial localmente en disco
""",

    # 4. CONSULTA EXITOSA (RELACIONES)
    "rag_04_consulta_relaciones_exito": f"""sequenceDiagram
{PARTICIPANTS_RAG_HEADER}
    User->>App: Como se relacionan los productos con los proveedores?
    App->>Emb: Vectoriza la pregunta del usuario
    Emb-->>App: Vector de la consulta
    App->>Chroma: similarity_search(query, k=4)
    Chroma-->>App: Chunks: TABLA ProductoProveedor, RELACION Producto_fk_ProductoProveedor
    Note over App: Construye Prompt: Basa tu respuesta UNICAMENTE en el contexto
    App->>LLM: Envia Prompt con Contexto del Esquema + Pregunta
    LLM-->>App: Se relacionan mediante la tabla intermedia ProductoProveedor (muchos a muchos)
    App-->>User: Muestra respuesta tecnica precisa en UI
""",

    # 5. CONSULTA FUERA DE ALCANCE (PREGUNTA DE REGISTROS)
    "rag_05_consulta_datos_sin_alucinacion": f"""sequenceDiagram
{PARTICIPANTS_RAG_HEADER}
    User->>App: Cuales son los 3 productos mas caros? (Pregunta sobre registros)
    App->>Emb: Vectoriza la pregunta
    Emb-->>App: Vector de la consulta
    App->>Chroma: similarity_search(query, k=4)
    Chroma-->>App: Fragmento recuperado: TABLA Producto (solo esquema, sin filas)
    Note over App: Inyecta contexto de esquema al LLM con regla de anclaje estricto
    App->>LLM: Envia contexto + Pregunta
    Note over LLM: LLM detecta que el contexto no contiene filas ni precios
    LLM-->>App: Esa informacion no se encuentra disponible en el esquema provisto
    App-->>User: Aclara que el catalogo no tiene datos de filas (Cero alucinacion)
"""
}

out_dir = Path(r"c:\proyectos\tp2-ia-utn\docs\diagramas_svg")
out_dir.mkdir(parents=True, exist_ok=True)

for name, mmd in rag_diagrams.items():
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

print("\nTodos los diagramas formales de RAG fueron generados con éxito!")
