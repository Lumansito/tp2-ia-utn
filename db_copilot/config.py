"""
Modulo de Configuracion -- Conexion a Base de Datos y LLM/Embeddings de Gemini.

Este proyecto usa exclusivamente la API de Google Gemini para el modelo de
lenguaje y para los embeddings. No hay fallback local ni soporte para OpenAI:
si falta la configuracion necesaria, las funciones de este modulo levantan
`ConfigError` en lugar de degradar silenciosamente (por ejemplo, a un
vectorizador local sin significado semantico).
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine, Engine

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
AUDIT_DB_PATH = DATA_DIR / "audit.sqlite"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# Motor local usado solo por scripts/seed_demo.py y por los tests. La app
# (app.py) siempre exige DATABASE_URL en el .env: no hay valor por defecto
# que apunte a una base "de mentira".
SQLITE_FALLBACK_URL = f"sqlite:///{DATA_DIR / 'ecommerce.db'}"

# Los nombres de modelo de Gemini cambian con frecuencia. Confirmarlos en
# https://ai.google.dev/gemini-api/docs/models antes de una demo importante.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_FALLBACK_MODEL = "gemini-2.5-flash-lite"
DEFAULT_GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"


class ConfigError(RuntimeError):
    """Falta una variable de entorno o credencial requerida para operar."""


def get_database_url(required: bool = True) -> Optional[str]:
    url = os.getenv("DATABASE_URL")
    if not url and required:
        raise ConfigError(
            "Falta DATABASE_URL en el .env. DB Copilot necesita la cadena de "
            "conexion de la base de datos que va a documentar y consultar "
            "(ver .env.example). El esquema siempre se lee de esa base; ya "
            "no se puede pegar ni subir un archivo .sql/.json."
        )
    return url


def get_engine(connection_string: Optional[str] = None) -> Engine:
    """
    Crea un motor de SQLAlchemy. Si no se pasa `connection_string`, usa
    DATABASE_URL del .env. Normaliza 'postgresql://' a 'postgresql+psycopg2://'.
    """
    url = connection_string or get_database_url(required=True)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})

    connect_args = {}
    statement_timeout_ms = os.getenv("DB_STATEMENT_TIMEOUT_MS")
    if statement_timeout_ms and "postgresql" in url:
        connect_args["options"] = f"-c statement_timeout={int(statement_timeout_ms)}"
    return create_engine(url, connect_args=connect_args)


def get_readonly_engine(default_engine: Optional[Engine] = None) -> Engine:
    """
    Motor para ejecutar SELECTs. Si DATABASE_URL_READONLY esta definida en el
    .env (recomendado: un usuario de base de datos con permisos de solo
    lectura), se usa esa conexion en vez de la principal. Es una capa extra
    de seguridad ademas de los guardrails de sql_guard.py.
    """
    readonly_url = os.getenv("DATABASE_URL_READONLY")
    if readonly_url:
        return get_engine(readonly_url)
    return default_engine if default_engine is not None else get_engine()


def get_llm(model_name: Optional[str] = None, temperature: float = 0.0):
    """
    Factory del LLM. Usa exclusivamente Google Gemini via `langchain-google-genai`.
    Lanza ConfigError si falta GOOGLE_API_KEY.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ConfigError(
            "Falta GOOGLE_API_KEY en el .env. DB Copilot usa exclusivamente "
            "la API de Google Gemini para el modelo de lenguaje (ver .env.example)."
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    model = model_name or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=api_key,
    )


def get_fallback_llm(temperature: float = 0.0):
    """
    LLM liviano de respaldo para cuando el modelo principal satura su cuota
    (429 RESOURCE_EXHAUSTED / 503 UNAVAILABLE). Pensado para usarse con
    `.with_fallbacks([...])` de LangChain, no con reintentos manuales.
    """
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", DEFAULT_GEMINI_FALLBACK_MODEL)
    return get_llm(model_name=fallback_model, temperature=temperature)


def get_embeddings():
    """
    Factory del modelo de embeddings. Usa exclusivamente
    `GoogleGenerativeAIEmbeddings` de Gemini. No hay fallback local: si falta
    la API key o la llamada falla, la excepcion se propaga tal cual para que
    la aplicacion no arranque en un estado degradado (sin embeddings semanticos).
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ConfigError(
            "Falta GOOGLE_API_KEY en el .env. Los embeddings de DB Copilot "
            "usan la API de Google Gemini; no hay vectorizador local de respaldo."
        )

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    model = get_embedding_model_name()
    # No se fija task_type a proposito: la libreria aplica automaticamente
    # RETRIEVAL_DOCUMENT en embed_documents() y RETRIEVAL_QUERY en
    # embed_query() cuando task_type queda sin especificar.
    return GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)


def get_embedding_model_name() -> str:
    return os.getenv("GEMINI_EMBEDDING_MODEL", DEFAULT_GEMINI_EMBEDDING_MODEL)


def verify_embeddings_available() -> None:
    """
    Hace una llamada real y minima a la API de embeddings para confirmar que
    la clave y el modelo funcionan. Se usa al arrancar la app: si falla, se
    corta la inicializacion en vez de seguir en un modo degradado.
    """
    embeddings = get_embeddings()
    embeddings.embed_query("ping de verificacion de DB Copilot")
