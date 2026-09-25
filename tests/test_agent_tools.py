"""
Tests de las herramientas del agente (list_tables, describe_table, run_select,
run_write, approve_pending_write) contra SQLite en memoria. No llaman al LLM
ni a Chroma: cubren guardrails + ejecucion + HITL + auditoria de punta a punta.
"""
import pytest
from sqlalchemy import create_engine, text

from db_copilot import agent, audit_store


@pytest.fixture(autouse=True)
def _isolated_audit_db(tmp_path, monkeypatch):
    """Cada test usa su propio archivo sqlite de auditoria, para no pisarse
    entre tests ni con datos reales de data/audit.sqlite."""
    monkeypatch.setattr(audit_store, "AUDIT_DB_PATH", tmp_path / "audit_test.sqlite")
    audit_store._init_db()
    yield


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT)"))
        conn.execute(text("INSERT INTO customers VALUES (1,'Ana','Perez'), (2,'Luis','Gomez')"))
    agent.set_agent_engine(eng)
    agent.set_schema_meta(None)
    return eng


@pytest.fixture
def tools(engine):
    return {t.name: t for t in agent.make_tools("pytest_thread")}


def test_list_tables(tools):
    assert "customers" in tools["list_tables"].invoke({})


def test_describe_table_unknown_table_lists_candidates(tools):
    result = tools["describe_table"].invoke({"table_name": "no_existe"})
    assert "No existe la tabla" in result
    assert "customers" in result


def test_run_select_returns_dataframe_and_summary(tools):
    result = tools["run_select"].invoke({"sql": "SELECT * FROM customers"})
    assert "Filas obtenidas: 2" in result
    df = agent.get_last_dataframe("pytest_thread")
    assert df is not None and len(df) == 2


def test_run_select_with_bad_column_returns_error_text_not_exception(tools):
    result = tools["run_select"].invoke({"sql": "SELECT nombre FROM customers"})
    assert "ERROR" in result


def test_run_select_blocks_ddl(tools):
    result = tools["run_select"].invoke({"sql": "DROP TABLE customers"})
    assert "BLOQUEADO" in result


def test_run_write_queues_for_approval_and_does_not_execute_yet(tools, engine):
    result = tools["run_write"].invoke({"sql": "UPDATE customers SET first_name='Cambiado' WHERE id=1"})
    assert "retenida para aprobacion humana" in result

    with engine.connect() as conn:
        name = conn.execute(text("SELECT first_name FROM customers WHERE id=1")).scalar()
    assert name == "Ana"  # todavia no se aplico

    pending = agent.get_pending_approvals("pytest_thread")
    assert len(pending) == 1


def test_approve_pending_write_executes_it(tools, engine):
    tools["run_write"].invoke({"sql": "UPDATE customers SET first_name='Cambiado' WHERE id=1"})
    action_id = agent.get_pending_approvals("pytest_thread")[0]["id"]

    msg = agent.approve_pending_write(action_id, approve=True, operator="Test")
    assert "aprobada y ejecutada" in msg

    with engine.connect() as conn:
        name = conn.execute(text("SELECT first_name FROM customers WHERE id=1")).scalar()
    assert name == "Cambiado"


def test_reject_pending_write_does_not_execute_it(tools, engine):
    tools["run_write"].invoke({"sql": "UPDATE customers SET first_name='Cambiado' WHERE id=1"})
    action_id = agent.get_pending_approvals("pytest_thread")[0]["id"]

    msg = agent.approve_pending_write(action_id, approve=False, operator="Test")
    assert "rechazada" in msg

    with engine.connect() as conn:
        name = conn.execute(text("SELECT first_name FROM customers WHERE id=1")).scalar()
    assert name == "Ana"
