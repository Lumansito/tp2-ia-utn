"""
Módulo de Configuración — Conexión a Base de Datos y Proveedores de LLM/Embeddings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, Engine

# Carga de variables de entorno desde .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
AUDIT_DB_PATH = DATA_DIR / "audit.sqlite"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)


def get_embedding_model_name() -> str:
    model_name = os.getenv("EMBEDDING_MODEL")
    if not model_name:
        raise ValueError("EMBEDDING_MODEL no está definida en el archivo .env.")
    return model_name


def get_engine(connection_string: str | None = None) -> Engine:
    url = connection_string or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError(
            "DATABASE_URL no está definida en el archivo .env. "
            "Configurá la cadena de conexión a la base de datos antes de iniciar la aplicación."
        )

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})

    return create_engine(url)


def get_llm(temperature: float = 0.0):
    provider = os.getenv("LLM_PROVIDER", "").upper()
    api_key = os.getenv("LLM_API_KEY")
    model_name = os.getenv("LLM_MODEL")

    if not provider:
        raise ValueError("LLM_PROVIDER no está definida en el archivo .env.")
    if not api_key:
        raise ValueError("LLM_API_KEY no está definida en el archivo .env.")
    if not model_name:
        raise ValueError("LLM_MODEL no está definida en el archivo .env.")

    if provider == "OPENAI":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=api_key,
        )

    if provider == "GEMINI":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            thinking_config={"include_thoughts": True},
        )

    raise ValueError(f"LLM_PROVIDER='{provider}' no soportado. Valores permitidos: 'OPENAI', 'GEMINI'.")


def get_embeddings():
    provider = os.getenv("LLM_PROVIDER", "").upper()
    api_key = os.getenv("LLM_API_KEY")
    model_name = os.getenv("EMBEDDING_MODEL")

    if not provider:
        raise ValueError("LLM_PROVIDER no está definida en el archivo .env.")
    if not api_key:
        raise ValueError("LLM_API_KEY no está definida en el archivo .env.")
    if not model_name:
        raise ValueError("EMBEDDING_MODEL no está definida en el archivo .env.")

    if provider == "OPENAI":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=model_name,
            api_key=api_key,
        )

    if provider == "GEMINI":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model=model_name,
            google_api_key=api_key,
        )

    raise ValueError(f"LLM_PROVIDER='{provider}' no soportado para embeddings. Valores permitidos: 'OPENAI', 'GEMINI'.")
