"""
Módulo RAG (Retrieval-Augmented Generation) para Esquema de Base de Datos.
Indexa documentos del catálogo relacional en Chroma y expone el retriever
así como la función de respuesta directa para el Modo Documentación / Esquema.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from db_copilot.config import CHROMA_DIR, get_embeddings, get_llm

_global_vector_store: Optional[Chroma] = None


def get_vector_store(
    persist_directory: Optional[Path] = None,
    embeddings=None
) -> Chroma:
    """
    Obtiene o inicializa el almacén vectorial Chroma.
    """
    global _global_vector_store
    if _global_vector_store is not None and persist_directory is None and embeddings is None:
        return _global_vector_store

    p_dir = str(persist_directory or CHROMA_DIR)
    emb = embeddings or get_embeddings()

    _global_vector_store = Chroma(
        collection_name="db_schema_docs",
        embedding_function=emb,
        persist_directory=p_dir,
    )
    return _global_vector_store


def index_schema_documents(
    schema_docs: List[Dict[str, Any]],
    persist_directory: Optional[Path] = None,
    embeddings=None
) -> Chroma:
    """
    Chunkea e indexa los documentos generados por schema_introspection en Chroma.
    Cada documento conserva sus metadatos (tipo: 'tabla'|'relacion'|'motor'|'indice', nombre).
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=80,
        separators=["\n\n", "\n", " - ", " ", ""],
    )

    documents: List[Document] = []
    for d in schema_docs:
        chunks = text_splitter.split_text(d["content"])
        for chunk in chunks:
            documents.append(
                Document(
                    page_content=chunk,
                    metadata=d.get("metadata", {}),
                )
            )

    vs = get_vector_store(persist_directory=persist_directory, embeddings=embeddings)
    
    # Limpiar colección existente antes de reindexar
    try:
        vs.reset_collection()
    except Exception:
        pass

    vs.add_documents(documents)
    return vs


def retrieve_schema_context(
    query: str,
    k: int = 4,
    tipo_filtro: Optional[str] = None,
    vector_store: Optional[Chroma] = None
) -> str:
    """
    Recupera fragmentos relevantes del esquema a partir de una consulta en lenguaje natural.
    Permite filtrar opcionalmente por tipo de metadato ('tabla', 'relacion', 'motor', 'indice').
    Si no se pasa filtro, combina inteligentemente definiciones de tablas y relaciones.
    """
    vs = vector_store or get_vector_store()
    
    if tipo_filtro:
        try:
            results = vs.similarity_search(query, k=k, filter={"tipo": tipo_filtro})
        except Exception:
            results = vs.similarity_search(query, k=k)
    else:
        # Búsqueda equilibrada: garantizar tanto tablas con sus columnas como relaciones FK
        results = []
        seen_ids = set()
        
        # 1. Recuperar tablas relevantes con sus columnas exactas
        try:
            tab_results = vs.similarity_search(query, k=max(k, 4), filter={"tipo": "tabla"})
            for doc in tab_results:
                doc_id = (doc.metadata.get("tipo"), doc.metadata.get("nombre"))
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    results.append(doc)
        except Exception:
            pass

        # 2. Recuperar relaciones FK relevantes
        try:
            rel_results = vs.similarity_search(query, k=max(k - 1, 3), filter={"tipo": "relacion"})
            for doc in rel_results:
                doc_id = (doc.metadata.get("tipo"), doc.metadata.get("nombre"))
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    results.append(doc)
        except Exception:
            pass

        # 3. Fallback general si la búsqueda filtrada no trajo nada
        if not results:
            results = vs.similarity_search(query, k=k)

    if not results:
        return "No se encontró información relevante del esquema en el índice vectorial."

    sections = []
    for doc in results:
        meta_tipo = doc.metadata.get("tipo", "doc").upper()
        meta_nombre = doc.metadata.get("nombre", "")
        header = f"[{meta_tipo}: {meta_nombre}]" if meta_nombre else f"[{meta_tipo}]"
        sections.append(f"{header}\n{doc.page_content}")

    return "\n\n---\n\n".join(sections)


def answer_schema_question(
    query: str,
    vector_store: Optional[Chroma] = None,
    llm=None,
    k: int = 4
) -> Dict[str, Any]:
    """
    MODO 1: Documentación / Esquema (RAG Puro).
    Responde preguntas sobre el modelo, relaciones, claves, índices y motor
    anclándose EXCLUSIVAMENTE en el contexto recuperado sin tocar la base de datos.
    """
    context = retrieve_schema_context(query, k=k, vector_store=vector_store)

    prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "Eres un asistente experto en arquitectura de bases de datos relacionales.\n"
         "Tu función es responder preguntas sobre el esquema de la base de datos, tipos de datos, relaciones y motor.\n"
         "Basa tu respuesta ÚNICAMENTE en el siguiente contexto extraído del catálogo del sistema.\n"
         "Si la respuesta no está en el contexto, aclara cordialmente qué datos no se encuentran disponibles.\n"
         "Sé preciso, conciso y técnico en español rioplatense o neutro.\n\n"
         "Contexto del Esquema:\n{context}"),
        ("human", "{question}"),
    ])

    model = llm or get_llm()

    try:
        chain = prompt | model | StrOutputParser()
        answer = chain.invoke({"context": context, "question": query})
    except Exception as exc:
        # Fallback informativo si la API no está configurada
        answer = (
            f"Contexto recuperado del esquema para '{query}':\n\n"
            f"{context}\n\n"
            f"(Nota: configure una clave de API válida de OpenAI o Gemini para síntesis con LLM. Detalle: {exc})"
        )

    return {
        "query": query,
        "answer": answer,
        "context": context,
    }
