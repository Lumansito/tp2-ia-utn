"""
Módulo de Configuración — Conexión a Base de Datos y Proveedores de LLM/Embeddings.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine, Engine

# Carga de variables de entorno desde .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# URL por defecto: PostgreSQL (o fallback local a SQLite si no está disponible)
DEFAULT_POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/ecommerce_db"
)
SQLITE_FALLBACK_URL = f"sqlite:///{DATA_DIR / 'ecommerce.db'}"


def get_engine(connection_string: Optional[str] = None) -> Engine:
    """
    Crea y retorna un motor de SQLAlchemy para el connection string especificado.
    Si no se pasa connection string, utiliza la variable DATABASE_URL del .env.
    Normaliza 'postgresql://' a 'postgresql+psycopg2://' automáticamente.
    """
    url = connection_string or os.getenv("DATABASE_URL") or DEFAULT_POSTGRES_URL
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


def get_llm(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.0,
):
    """
    Factory para instanciar el modelo LLM según el proveedor configurado en .env (OpenAI o Gemini).
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "AUTO")).upper()
    openai_key = api_key if provider == "OPENAI" else os.getenv("OPENAI_API_KEY")
    gemini_key = api_key if provider == "GEMINI" else os.getenv("GOOGLE_API_KEY")

    # Sanitizar claves en caso de prefijos residuales
    if openai_key and "OPENAI_API_KEY=" in openai_key:
        openai_key = openai_key.replace("OPENAI_API_KEY=", "").strip()
    if gemini_key and "OPENAI_API_KEY=" in gemini_key:
        gemini_key = gemini_key.replace("OPENAI_API_KEY=", "").strip()
    if gemini_key and "GOOGLE_API_KEY=" in gemini_key:
        gemini_key = gemini_key.replace("GOOGLE_API_KEY=", "").strip()

    if provider == "AUTO":
        if gemini_key and "AIza" in gemini_key or "AQ." in (gemini_key or ""):
            provider = "GEMINI"
        elif openai_key and "sk-" in openai_key:
            provider = "OPENAI"
        elif gemini_key:
            provider = "GEMINI"
        elif openai_key:
            provider = "OPENAI"
        else:
            provider = "GEMINI"

    if provider == "OPENAI":
        from langchain_openai import ChatOpenAI
        model = model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=openai_key,
        )
    elif provider == "GEMINI":
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        kwargs = {
            "model": model,
            "temperature": temperature,
            "google_api_key": gemini_key,
        }
        # Habilitar captura de thinking si el modelo lo admite
        try:
            kwargs["thinking_config"] = {"include_thoughts": True}
            return ChatGoogleGenerativeAI(**kwargs)
        except Exception:
            kwargs.pop("thinking_config", None)
            return ChatGoogleGenerativeAI(**kwargs)
    else:
        raise ValueError(f"Proveedor '{provider}' no soportado. Use 'OPENAI' o 'GEMINI'.")


def get_embeddings(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """
    Factory para instanciar el modelo de Embeddings.
    Si se dispone de OpenAI lo usa; en caso contrario recurre al vectorizador local determinístico.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "AUTO")).upper()
    openai_key = api_key if provider == "OPENAI" else os.getenv("OPENAI_API_KEY")

    is_dummy_openai = not openai_key or "tu-api-key" in openai_key or openai_key == "sk-proj-tu-api-key-de-openai-aqui"
    if provider == "OPENAI" and not is_dummy_openai:
        from langchain_openai import OpenAIEmbeddings
        try:
            return OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=openai_key,
            )
        except Exception:
            pass

    # Fallback local determinístico con HashingVectorizer (no consume cuota de API ni requiere permisos externos)
    from langchain_core.embeddings import Embeddings
    from sklearn.feature_extraction.text import HashingVectorizer

    class LocalHashEmbeddings(Embeddings):
        def __init__(self, n_features: int = 1024):
            self.vectorizer = HashingVectorizer(n_features=n_features, alternate_sign=False, norm="l2")

        def embed_documents(self, texts):
            matrix = self.vectorizer.transform(texts)
            return matrix.toarray().tolist()

        def embed_query(self, text):
            return self.vectorizer.transform([text]).toarray()[0].tolist()

    return LocalHashEmbeddings()


