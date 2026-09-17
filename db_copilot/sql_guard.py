"""
Módulo de Seguridad y Guardrails SQL (sql_guard.py).
Valida sintaxis, verifica que sea una única sentencia, clasifica entre
lectura (SELECT), escritura controlada (UPDATE/DELETE) y sentencias prohibidas (DROP/ALTER/CREATE),
e inyecta cláusulas LIMIT de seguridad automáticas.
"""

import re
from typing import Dict, Any, Optional

try:
    import sqlglot
    from sqlglot import exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False


def validate_and_classify_sql(
    sql_text: str,
    default_limit: int = 500,
    dialect: str = "postgres"
) -> Dict[str, Any]:
    """
    Inspecciona y sanitiza una sentencia SQL.
    
    Retorna un diccionario con:
    - is_valid: bool (True si la sentencia es válida y permitida)
    - classification: "SELECT" | "WRITE" | "FORBIDDEN" | "INVALID"
    - sanitized_sql: str (SQL normalizado y con LIMIT si aplica)
    - has_limit: bool (True si ya tenía LIMIT o se le inyectó)
    - warning: Optional[str] (advertencias, ej: UPDATE sin WHERE)
    - error: Optional[str] (motivo de rechazo en caso de no ser válida)
    """
    cleaned_sql = sql_text.strip()
    if cleaned_sql.endswith(";"):
        cleaned_sql = cleaned_sql[:-1].strip()

    if not cleaned_sql:
        return {
            "is_valid": False,
            "classification": "INVALID",
            "sanitized_sql": "",
            "has_limit": False,
            "warning": None,
            "error": "La consulta SQL está vacía.",
        }

    # 1. Validación con sqlglot (motor AST formal)
    if HAS_SQLGLOT:
        try:
            # Parsear todas las expresiones encontradas
            expressions = sqlglot.parse(cleaned_sql, read=dialect)
        except Exception as e:
            return {
                "is_valid": False,
                "classification": "INVALID",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": f"Error de sintaxis SQL: {e}",
            }

        # Rechazo estricto de sentencias encadenadas (; DROP TABLE, etc.)
        if len(expressions) > 1:
            return {
                "is_valid": False,
                "classification": "FORBIDDEN",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": "Sentencias múltiples encadenadas detectadas. Por seguridad, solo se permite exactamente una sentencia por ejecución.",
            }

        ast = expressions[0]
        if ast is None:
            return {
                "is_valid": False,
                "classification": "INVALID",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": "No se pudo interpretar la sentencia SQL.",
            }

        # Caso A: SELECT
        if isinstance(ast, exp.Select):
            has_limit = ast.args.get("limit") is not None
            if not has_limit:
                # Inyección preventiva de LIMIT para no desbordar memoria
                ast = ast.limit(default_limit)
                has_limit = True

            sanitized = ast.sql(dialect=dialect)
            return {
                "is_valid": True,
                "classification": "SELECT",
                "sanitized_sql": sanitized,
                "has_limit": has_limit,
                "warning": None,
                "error": None,
            }

        # Caso B: UPDATE o DELETE (Escritura que requiere aprobación humana)
        elif isinstance(ast, (exp.Update, exp.Delete)):
            has_where = ast.args.get("where") is not None
            warning = None
            if not has_where:
                warning = "⚠️ ADVERTENCIA: La sentencia no contiene cláusula WHERE. Afectará todas las filas de la tabla."

            return {
                "is_valid": True,
                "classification": "WRITE",
                "sanitized_sql": ast.sql(dialect=dialect),
                "has_limit": False,
                "warning": warning,
                "error": None,
            }

        forbidden_types = tuple(
            getattr(exp, name)
            for name in ("Drop", "Alter", "Create", "Insert", "Command", "Truncate")
            if hasattr(exp, name)
        )
        if forbidden_types and isinstance(ast, forbidden_types):
            stmt_type = ast.key.upper() if hasattr(ast, "key") else "DDL/DCL"
            return {
                "is_valid": False,
                "classification": "FORBIDDEN",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": f"Operación '{stmt_type}' no permitida. Por política de seguridad, las operaciones DDL (DROP, ALTER, CREATE, TRUNCATE) están bloqueadas.",
            }
        else:
            return {
                "is_valid": False,
                "classification": "FORBIDDEN",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": f"Tipo de sentencia '{type(ast).__name__}' no autorizada.",
            }

    # 2. Fallback por expresiones regulares si sqlglot no estuviese disponible
    else:
        if ";" in cleaned_sql:
            return {
                "is_valid": False,
                "classification": "FORBIDDEN",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": "Sentencias múltiples detectadas con ';'.",
            }

        first_word = cleaned_sql.split()[0].upper()
        if first_word == "SELECT":
            has_limit = bool(re.search(r"\blimit\s+\d+\b", cleaned_sql, re.IGNORECASE))
            sanitized = cleaned_sql if has_limit else f"{cleaned_sql} LIMIT {default_limit}"
            return {
                "is_valid": True,
                "classification": "SELECT",
                "sanitized_sql": sanitized,
                "has_limit": True,
                "warning": None,
                "error": None,
            }
        elif first_word in ("UPDATE", "DELETE"):
            has_where = bool(re.search(r"\bwhere\b", cleaned_sql, re.IGNORECASE))
            warning = "⚠️ ADVERTENCIA: Sin cláusula WHERE." if not has_where else None
            return {
                "is_valid": True,
                "classification": "WRITE",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": warning,
                "error": None,
            }
        else:
            return {
                "is_valid": False,
                "classification": "FORBIDDEN",
                "sanitized_sql": cleaned_sql,
                "has_limit": False,
                "warning": None,
                "error": f"Comando '{first_word}' denegado por guardrails de seguridad.",
            }
