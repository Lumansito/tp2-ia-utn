"""
Tests de config.py: sin credenciales, las factories deben fallar con un
mensaje claro (ConfigError), no con un fallback silencioso.
"""
import pytest

from db_copilot.config import ConfigError, get_llm, get_embeddings, get_database_url


def test_get_llm_without_google_api_key_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        get_llm()


def test_get_embeddings_without_google_api_key_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        get_embeddings()


def test_get_database_url_without_env_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError):
        get_database_url(required=True)


def test_get_database_url_optional_returns_none(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_database_url(required=False) is None
