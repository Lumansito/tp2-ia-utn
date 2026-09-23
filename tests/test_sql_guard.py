"""
Tests del validador de SQL (sqlglot). No requieren red ni credenciales.
"""
import pytest

from db_copilot.sql_guard import validate_and_classify_sql


@pytest.mark.parametrize("sql,expected", [
    ("SELECT * FROM customers", "SELECT"),
    ("SELECT * FROM orders WHERE status = 'pending' LIMIT 10", "SELECT"),
    ("SELECT id FROM a UNION SELECT id FROM b", "SELECT"),
    ("SELECT id FROM a INTERSECT SELECT id FROM b", "SELECT"),
    ("WITH x AS (SELECT 1 AS n) SELECT * FROM x", "SELECT"),
    ("SELECT * FROM auditoria WHERE accion = 'DROP'", "SELECT"),
    ("/* comentario */ SELECT * FROM customers", "SELECT"),
    ("UPDATE orders SET status = 'shipped' WHERE id = 1", "WRITE"),
    ("UPDATE orders SET status = 'cancelled'", "WRITE"),
    ("DELETE FROM orders WHERE id = 1", "WRITE"),
    ("INSERT INTO orders (id, status) VALUES (1, 'new')", "WRITE"),
    ("SELECT * FROM customers; DROP TABLE orders;", "FORBIDDEN"),
    ("DROP TABLE products;", "FORBIDDEN"),
    ("ALTER TABLE products ADD COLUMN x INT;", "FORBIDDEN"),
    ("TRUNCATE TABLE products;", "FORBIDDEN"),
    ("CREATE TABLE x (id INT);", "FORBIDDEN"),
    ("", "INVALID"),
    ("ESTO NO ES SQL(((", "INVALID"),
])
def test_classification(sql, expected):
    result = validate_and_classify_sql(sql, dialect="postgres")
    assert result["classification"] == expected, result


def test_select_without_limit_gets_one_injected():
    result = validate_and_classify_sql("SELECT * FROM customers", dialect="postgres")
    assert result["is_valid"]
    assert "LIMIT 500" in result["sanitized_sql"]


def test_select_with_explicit_limit_is_kept():
    result = validate_and_classify_sql("SELECT * FROM orders LIMIT 10", dialect="postgres")
    assert "LIMIT 10" in result["sanitized_sql"]
    assert "LIMIT 500" not in result["sanitized_sql"]


def test_update_without_where_has_warning():
    result = validate_and_classify_sql("UPDATE orders SET status = 'x'", dialect="postgres")
    assert result["classification"] == "WRITE"
    assert result["warning"] is not None


def test_update_with_where_has_no_warning():
    result = validate_and_classify_sql("UPDATE orders SET status = 'x' WHERE id = 1", dialect="postgres")
    assert result["classification"] == "WRITE"
    assert result["warning"] is None


def test_multi_statement_is_blocked_even_if_first_is_safe():
    result = validate_and_classify_sql("SELECT 1; SELECT 2;", dialect="postgres")
    assert not result["is_valid"]
    assert result["classification"] == "FORBIDDEN"


def test_string_literal_containing_forbidden_word_is_not_a_false_positive():
    result = validate_and_classify_sql("SELECT * FROM logs WHERE action = 'DROP TABLE'", dialect="postgres")
    assert result["classification"] == "SELECT"
