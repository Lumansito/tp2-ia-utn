"""
Modulo RAG (Retrieval-Augmented Generation) para el esquema de la base de datos.
Indexa documentos del catalogo relacional en Chroma usando embeddings de
Gemini y expone el retriever y la respuesta directa del Modo Documentacion.
"""

import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from db_copilot.config import CHROMA_DIR, get_embeddings, get_llm, get_embedding_model_name

_global_vector_store: Optional[Chroma] = None
_global_vector_store_key: Optional[str] = None


def _collection_name() -> str:
    """
    El nombre de la coleccion incluye el modelo de embeddings activo. Los
    distintos modelos de embeddings producen vectores de distinta dimension;
    si se cambia de modelo sin cambiar de coleccion, Chroma falla al mezclar
    dimensiones. Nombrar la coleccion por modelo evita ese error silencioso.
    """
    model = get_embedding_model_name()
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", model)
    return f"db_schema_docs_{safe}"


def get_vector_store(persist_directory: Optional[Path] = None, embeddings=None) -> Chroma:
    """Obtiene o inicializa el almacen vectorial Chroma."""
    global _global_vector_store, _global_vector_store_key

    collection_name = _collection_name()
    cache_key = f"{persist_directory}|{collection_name}"
    if _global_vector_store is not None and embeddings is None and cache_key == _global_vector_store_key:
        return _global_vector_store

    p_dir = str(persist_directory or CHROMA_DIR)
    emb = embeddings or get_embeddings()

    _global_vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=emb,
        persist_directory=p_dir,
    )
    _global_vector_store_key = cache_key
    return _global_vector_store


def index_schema_documents(
    schema_docs: List[Dict[str, Any]],
    persist_directory: Optional[Path] = None,
    embeddings=None,
) -> Chroma:
    """
    Chunkea e indexa los documentos generados por schema_introspection en
    Chroma. Cada documento conserva sus metadatos (tipo: tabla|relacion|
    motor|indice, nombre).
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
            documents.append(Document(page_content=chunk, metadata=d.get("metadata", {})))

    vs = get_vector_store(persist_directory=persist_directory, embeddings=embeddings)
    try:
        vs.reset_collection()
    except Exception:
        pass

    if documents:
        vs.add_documents(documents)
    return vs


def retrieve_schema_context(
    query: str,
    k: int = 4,
    tipo_filtro: Optional[str] = None,
    vector_store: Optional[Chroma] = None,
) -> str:
    """
    Recupera fragmentos relevantes del esquema a partir de una consulta en
    lenguaje natural. Permite filtrar opcionalmente por tipo de metadato
    ('tabla', 'relacion', 'motor', 'indice'). Sin filtro, combina
    inteligentemente definiciones de tablas y relaciones.
    """
    vs = vector_store or get_vector_store()

    if tipo_filtro:
        try:
            results = vs.similarity_search(query, k=k, filter={"tipo": tipo_filtro})
        except Exception:
            results = vs.similarity_search(query, k=k)
    else:
        results = []
        seen_ids = set()

        try:
            tab_results = vs.similarity_search(query, k=max(k, 4), filter={"tipo": "tabla"})
            for doc in tab_results:
                doc_id = (doc.metadata.get("tipo"), doc.metadata.get("nombre"))
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    results.append(doc)
        except Exception:
            pass

        try:
            rel_results = vs.similarity_search(query, k=max(k - 1, 3), filter={"tipo": "relacion"})
            for doc in rel_results:
                doc_id = (doc.metadata.get("tipo"), doc.metadata.get("nombre"))
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    results.append(doc)
        except Exception:
            pass

        if not results:
            results = vs.similarity_search(query, k=k)

    if not results:
        return "No se encontro informacion relevante del esquema en el indice vectorial."

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
    k: int = 4,
) -> Dict[str, Any]:
    """
    MODO 1: Documentacion / Esquema (RAG puro). Responde preguntas sobre el
    modelo, relaciones, claves e indices anclandose EXCLUSIVAMENTE en el
    contexto recuperado, sin tocar la base de datos.
    """
    context = retrieve_schema_context(query, k=k, vector_store=vector_store)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "Eres un asistente experto en arquitectura de bases de datos relacionales.\n"
         "Tu funcion es responder preguntas sobre el esquema de la base de datos, tipos de datos, relaciones y motor.\n"
         "Basa tu respuesta UNICAMENTE en el siguiente contexto extraido del catalogo del sistema.\n"
         "Si la respuesta no esta en el contexto, aclara cordialmente que datos no se encuentran disponibles.\n"
         "Se preciso, conciso y tecnico en espanol rioplatense o neutro.\n\n"
         "Contexto del Esquema:\n{context}"),
        ("human", "{question}"),
    ])

    model = llm or get_llm()
    chain = prompt | model | StrOutputParser()
    answer = chain.invoke({"context": context, "question": query})

    return {"query": query, "answer": answer, "context": context}
