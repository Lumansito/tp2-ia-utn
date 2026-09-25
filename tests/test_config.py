"""
Tests de config.py contra el .env generico (LLM_PROVIDER/LLM_API_KEY/LLM_MODEL/
EMBEDDING_MODEL). Sin credenciales, las factories deben fallar con un mensaje
claro (ValueError), no con un fallback silencioso.
"""
import pytest

from db_copilot.config import get_llm, get_embeddings, get_engine, get_embedding_model_name


def _clear_llm_env(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "EMBEDDING_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_get_llm_without_provider_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        get_llm()


def test_get_llm_without_api_key_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "GEMINI")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_llm()


def test_get_llm_without_model_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "GEMINI")
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        get_llm()


def test_get_llm_with_unsupported_provider_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "COHERE")
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    monkeypatch.setenv("LLM_MODEL", "algo")
    with pytest.raises(ValueError, match="no soportado"):
        get_llm()


def test_get_embeddings_without_provider_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        get_embeddings()


def test_get_embeddings_without_embedding_model_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "GEMINI")
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    with pytest.raises(ValueError, match="EMBEDDING_MODEL"):
        get_embeddings()


def test_get_embedding_model_name_without_env_raises(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    with pytest.raises(ValueError, match="EMBEDDING_MODEL"):
        get_embedding_model_name()


def test_get_embedding_model_name_returns_value(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
    assert get_embedding_model_name() == "models/gemini-embedding-001"


def test_get_engine_without_database_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        get_engine()


def test_get_engine_normalizes_plain_postgresql_scheme(monkeypatch):
    # Requiere psycopg2 instalado (esta en requirements.txt); si el entorno
    # que corre los tests no lo tiene instalado, se saltea en vez de fallar.
    pytest.importorskip("psycopg2")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine = get_engine("postgresql://user:pass@localhost:5432/db")
    assert engine.url.drivername == "postgresql+psycopg2"


def test_get_engine_accepts_sqlite():
    engine = get_engine("sqlite:///:memory:")
    assert engine.dialect.name == "sqlite"
