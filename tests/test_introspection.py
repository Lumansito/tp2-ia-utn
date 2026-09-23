"""
Tests de introspeccion de esquema contra una base SQLite temporal en memoria,
sin depender de PostgreSQL ni de ninguna API externa.
"""
from sqlalchemy import create_engine, text

from db_copilot.schema_introspection import (
    introspect_database,
    generate_natural_language_docs,
    schema_fingerprint,
    generate_dbml,
)


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                total REAL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """))
        conn.execute(text("INSERT INTO customers (id, first_name, last_name) VALUES (1, 'Ana', 'Perez')"))
        conn.execute(text("INSERT INTO orders (id, customer_id, total) VALUES (1, 1, 100.0)"))
    return engine


def test_introspect_finds_tables_and_fks():
    engine = _make_engine()
    meta = introspect_database(engine)
    assert set(meta["tables"].keys()) == {"customers", "orders"}
    orders_fks = meta["tables"]["orders"]["foreign_keys"]
    assert len(orders_fks) == 1
    assert orders_fks[0]["referred_table"] == "customers"


def test_natural_language_docs_include_table_and_relation_docs():
    engine = _make_engine()
    meta = introspect_database(engine)
    docs = generate_natural_language_docs(meta)
    tipos = [d["metadata"]["tipo"] for d in docs]
    assert "tabla" in tipos
    assert "relacion" in tipos
    assert any("orders" in d["content"] for d in docs)


def test_fingerprint_changes_when_schema_changes():
    engine = _make_engine()
    meta1 = introspect_database(engine)
    fp1 = schema_fingerprint(meta1)

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE customers ADD COLUMN email TEXT"))
    meta2 = introspect_database(engine)
    fp2 = schema_fingerprint(meta2)

    assert fp1 != fp2


def test_fingerprint_stable_for_same_schema():
    engine = _make_engine()
    fp1 = schema_fingerprint(introspect_database(engine))
    fp2 = schema_fingerprint(introspect_database(engine))
    assert fp1 == fp2


def test_generate_dbml_includes_tables_and_refs():
    engine = _make_engine()
    meta = introspect_database(engine)
    dbml = generate_dbml(meta)
    assert "Table customers" in dbml
    assert "Table orders" in dbml
    assert "Ref: orders.customer_id > customers.id" in dbml
