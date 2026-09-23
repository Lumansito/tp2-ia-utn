"""
Modulo de Seguridad y Guardrails SQL (sql_guard.py).

Valida sintaxis mediante un parser AST formal (sqlglot), verifica que sea
una unica sentencia, clasifica entre lectura (SELECT/UNION/...), escritura
controlada (INSERT/UPDATE/DELETE, sujeta a aprobacion humana) y sentencias
prohibidas (DDL: DROP/ALTER/CREATE/TRUNCATE), e inyecta clausulas LIMIT de
seguridad automaticas en las lecturas.

sqlglot es una dependencia obligatoria: no hay alternativa por expresiones
regulares. Un guardrail por regex es trivialmente evadible con comentarios
SQL, cadenas literales o saltos de linea, y ese era justamente el argumento
para usar sqlglot en primer lugar.
"""

from typing import Dict, Any

import sqlglot
from sqlglot import exp

# Nodos AST que sqlglot usa para sentencias de lectura. Ademas de SELECT,
# una consulta con UNION/INTERSECT/EXCEPT en el nivel superior no es un
# exp.Select sino uno de estos otros tipos -- antes se bloqueaban por error.
_READ_TYPES = tuple(
    t for t in (
        getattr(exp, "Select", None),
        getattr(exp, "Union", None),
        getattr(exp, "Intersect", None),
        getattr(exp, "Except", None),
    ) if t is not None
)

# INSERT/UPDATE/DELETE son mutaciones: quedan retenidas para aprobacion
# humana (HITL) en lugar de bloquearse. Un INSERT no es tan riesgoso como un
# DROP, pero tampoco es una lectura: por eso no entra en _READ_TYPES.
_WRITE_TYPES = tuple(
    t for t in (
        getattr(exp, "Insert", None),
        getattr(exp, "Update", None),
        getattr(exp, "Delete", None),
    ) if t is not None
)

# DDL/DCL estrictamente prohibido, sin excepciones.
_FORBIDDEN_TYPES = tuple(
    t for t in (
        getattr(exp, "Drop", None),
        getattr(exp, "Alter", None),
        getattr(exp, "Create", None),
        getattr(exp, "Truncate", None),
        getattr(exp, "Command", None),
        getattr(exp, "Grant", None),
    ) if t is not None
)


def _invalid(error: str) -> Dict[str, Any]:
    return {
        "is_valid": False,
        "classification": "INVALID",
        "sanitized_sql": "",
        "has_limit": False,
        "warning": None,
        "error": error,
    }


def _forbidden(sql: str, error: str) -> Dict[str, Any]:
    return {
        "is_valid": False,
        "classification": "FORBIDDEN",
        "sanitized_sql": sql,
        "has_limit": False,
        "warning": None,
        "error": error,
    }


def validate_and_classify_sql(
    sql_text: str,
    default_limit: int = 500,
    dialect: str = "postgres",
) -> Dict[str, Any]:
    """
    Inspecciona y sanitiza una sentencia SQL.

    Retorna un diccionario con:
    - is_valid: bool (True si la sentencia es valida y permitida)
    - classification: "SELECT" | "WRITE" | "FORBIDDEN" | "INVALID"
    - sanitized_sql: str (SQL normalizado, con LIMIT inyectado si aplica)
    - has_limit: bool (True si ya tenia LIMIT o se le inyecto)
    - warning: Optional[str] (advertencias, ej: UPDATE/DELETE sin WHERE)
    - error: Optional[str] (motivo de rechazo en caso de no ser valida)
    """
    cleaned_sql = sql_text.strip()
    if cleaned_sql.endswith(";"):
        cleaned_sql = cleaned_sql[:-1].strip()

    if not cleaned_sql:
        return _invalid("La consulta SQL esta vacia.")

    try:
        expressions = sqlglot.parse(cleaned_sql, read=dialect)
    except Exception as e:
        return _invalid(f"Error de sintaxis SQL: {e}")

    expressions = [e for e in expressions if e is not None]
    if len(expressions) == 0:
        return _invalid("No se pudo interpretar la sentencia SQL.")
    if len(expressions) > 1:
        return _forbidden(
            cleaned_sql,
            "Sentencias multiples encadenadas detectadas. Por seguridad, solo "
            "se permite exactamente una sentencia por ejecucion.",
        )

    ast = expressions[0]

    # Caso A: lectura (SELECT, o UNION/INTERSECT/EXCEPT de SELECTs, incluye WITH)
    if isinstance(ast, _READ_TYPES):
        has_limit = ast.args.get("limit") is not None
        if not has_limit:
            ast = ast.limit(default_limit)
            has_limit = True

        return {
            "is_valid": True,
            "classification": "SELECT",
            "sanitized_sql": ast.sql(dialect=dialect),
            "has_limit": has_limit,
            "warning": None,
            "error": None,
        }

    # Caso B: escritura (INSERT/UPDATE/DELETE) -> requiere aprobacion humana
    if isinstance(ast, _WRITE_TYPES):
        warning = None
        if isinstance(ast, (exp.Update, exp.Delete)):
            has_where = ast.args.get("where") is not None
            if not has_where:
                warning = (
                    "ADVERTENCIA: la sentencia no contiene clausula WHERE. "
                    "Afectara todas las filas de la tabla."
                )
        elif isinstance(ast, exp.Insert):
            warning = "Sentencia INSERT: agrega filas nuevas a la tabla."

        return {
            "is_valid": True,
            "classification": "WRITE",
            "sanitized_sql": ast.sql(dialect=dialect),
            "has_limit": False,
            "warning": warning,
            "error": None,
        }

    # Caso C: DDL/DCL prohibido sin excepcion
    if isinstance(ast, _FORBIDDEN_TYPES):
        stmt_type = ast.key.upper() if hasattr(ast, "key") else "DDL/DCL"
        return _forbidden(
            cleaned_sql,
            f"Operacion '{stmt_type}' no permitida. Por politica de seguridad, "
            f"las operaciones DDL (DROP, ALTER, CREATE, TRUNCATE) estan bloqueadas.",
        )

    # Cualquier otro tipo de nodo no contemplado explicitamente se rechaza.
    return _forbidden(
        cleaned_sql,
        f"Tipo de sentencia '{type(ast).__name__}' no autorizada.",
    )
