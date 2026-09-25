"""
Introspeccion de esquema y generacion de documentos NLP para el RAG.

El esquema se lee siempre en vivo desde la base de datos conectada
(DATABASE_URL). No hay carga manual de un DDL o JSON externo: eso hacia que
el sistema respondiera sobre un esquema distinto del que realmente
consultaba, y solo servia para la base de demo de este proyecto.

El contexto de negocio (que significa cada tabla, sinonimos en espanol,
aclaraciones sobre columnas) ya no esta escrito a mano para 15 tablas fijas:
se toma de los COMMENT ON TABLE / COMMENT ON COLUMN de la propia base. Si la
base no tiene comentarios, el documento generado es mas escueto, pero sigue
siendo correcto para cualquier esquema.
"""

import hashlib
import json
from typing import Dict, Any, List, Optional

from sqlalchemy import inspect, text, Engine


def introspect_database(engine: Engine, schema: Optional[str] = None) -> Dict[str, Any]:
    """
    Inspecciona la base de datos conectada mediante SQLAlchemy inspect().
    Devuelve un diccionario estructurado con metadatos del motor, tablas,
    columnas, tipos, comentarios, claves primarias, claves foraneas e indices.

    `schema` permite restringir la introspeccion a un schema de PostgreSQL en
    particular (por defecto None = el schema por defecto de la conexion,
    tipicamente "public"). Se ignora en SQLite.
    """
    inspector = inspect(engine)
    dialect_name = engine.dialect.name

    server_version = "Desconocida"
    try:
        with engine.connect() as conn:
            if dialect_name == "postgresql":
                ver = conn.execute(text("SELECT version();")).scalar()
                server_version = " ".join(ver.split()[:2]) if ver else "PostgreSQL"
            elif dialect_name == "sqlite":
                ver = conn.execute(text("SELECT sqlite_version();")).scalar()
                server_version = f"SQLite {ver}"
    except Exception:
        server_version = dialect_name.capitalize()

    kwargs = {"schema": schema} if (schema and dialect_name == "postgresql") else {}
    table_names = inspector.get_table_names(**kwargs)
    tables_meta = {}

    for table in table_names:
        columns = inspector.get_columns(table, **kwargs)
        pk_constraint = inspector.get_pk_constraint(table, **kwargs)
        fks = inspector.get_foreign_keys(table, **kwargs)
        indexes = inspector.get_indexes(table, **kwargs)

        table_comment = None
        try:
            comment_info = inspector.get_table_comment(table, **kwargs)
            table_comment = comment_info.get("text") if comment_info else None
        except NotImplementedError:
            table_comment = None
        except Exception:
            table_comment = None

        row_count = _estimate_row_count(engine, table, schema, dialect_name)

        tables_meta[table] = {
            "comment": table_comment,
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default")) if col.get("default") is not None else None,
                    "comment": col.get("comment"),
                }
                for col in columns
            ],
            "primary_key": pk_constraint.get("constrained_columns", []) or [],
            "foreign_keys": [
                {
                    "constrained_columns": fk.get("constrained_columns", []),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns", []),
                }
                for fk in fks
            ],
            "indexes": [
                {
                    "name": idx.get("name"),
                    "column_names": idx.get("column_names", []),
                    "unique": idx.get("unique", False),
                }
                for idx in indexes
            ],
            "row_count": row_count,
        }

    return {
        "engine": dialect_name,
        "version": server_version,
        "schema": schema,
        "tables": tables_meta,
    }


def _estimate_row_count(engine: Engine, table: str, schema: Optional[str], dialect_name: str) -> Optional[int]:
    """
    En PostgreSQL usa la estimacion de `pg_class.reltuples` (instantanea, no
    escanea la tabla) en lugar de COUNT(*), que en una base grande puede
    tardar segundos por tabla y hacer lento cada arranque de la app. En
    SQLite (bases chicas de demo) sigue usando COUNT(*).
    """
    try:
        with engine.connect() as conn:
            if dialect_name == "postgresql":
                qualified = f"{schema}.{table}" if schema else table
                estimate = conn.execute(
                    text("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(:t)"),
                    {"t": qualified},
                ).scalar()
                if estimate is not None and estimate >= 0:
                    return int(estimate)
                return conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    except Exception:
        return None


def schema_fingerprint(schema_meta: Dict[str, Any]) -> str:
    """
    Hash estable de la forma del esquema (tablas, columnas, tipos y FKs).
    Se usa para decidir si hace falta reindexar el RAG: si el fingerprint no
    cambio desde la ultima vez, no hace falta volver a llamar a la API de
    embeddings ni a Chroma en cada arranque.
    """
    tables = schema_meta.get("tables", {})
    shape = {}
    for name, meta in sorted(tables.items()):
        shape[name] = {
            "columns": [(c["name"], c["type"]) for c in meta.get("columns", [])],
            "foreign_keys": [
                (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                for fk in meta.get("foreign_keys", [])
            ],
        }
    payload = json.dumps(shape, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_natural_language_docs(schema_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convierte los metadatos estructurados en documentos de texto en lenguaje
    natural, disenados para ser vectorizados y consultados via RAG.

    Genera:
    - 1 documento del motor y dialecto.
    - 1 documento por cada tabla (columnas, tipos, PK, filas, comentario de la
      tabla y de sus columnas si la base los tiene).
    - 1 documento por cada relacion de clave foranea (FK).
    - 1 documento por cada indice relevante.
    """
    docs = []
    engine_name = schema_meta.get("engine", "postgresql")
    version = schema_meta.get("version", "N/A")
    tables = schema_meta.get("tables", {})

    engine_notes = {
        "postgresql": "PostgreSQL es un motor relacional avanzado con soporte para tipos estrictos, JSONB, indices B-Tree/GIN/GiST, funciones de ventana y transacciones ACID completas.",
        "sqlite": "SQLite es un motor relacional ligero basado en archivos, adecuado para prototipos y pruebas locales. Tipado dinamico con afinidad de tipos.",
    }
    engine_note = engine_notes.get(engine_name.lower(), "Motor de base de datos relacional compatible con SQL estandar.")

    doc_engine = (
        f"MOTOR DE BASE DE DATOS Y ENTORNO:\n"
        f"Motor configurado: {engine_name.upper()}\n"
        f"Version: {version}\n"
        f"Dialecto SQLAlchemy: {engine_name}\n"
        f"Caracteristicas: {engine_note}\n"
        f"Tablas disponibles en la base de datos: {', '.join(tables.keys())}."
    )
    docs.append({"content": doc_engine, "metadata": {"tipo": "motor", "nombre": engine_name}})

    for table_name, meta in tables.items():
        cols_desc = []
        pk_list = meta.get("primary_key", [])
        for col in meta.get("columns", []):
            pk_flag = " [CLAVE PRIMARIA (PK)]" if col["name"] in pk_list else ""
            null_flag = "opcional (NULL)" if col.get("nullable") else "obligatorio (NOT NULL)"
            comment_flag = f" -- {col['comment']}" if col.get("comment") else ""
            cols_desc.append(f"  - Columna '{col['name']}': Tipo {col['type']}, {null_flag}{pk_flag}{comment_flag}")

        rows_info = (
            f"Contiene aproximadamente {meta['row_count']} registros."
            if meta.get("row_count") is not None
            else "Cantidad de filas variable."
        )
        table_comment = meta.get("comment")
        comment_text = f"\nDescripcion de negocio (segun COMMENT ON TABLE): {table_comment}" if table_comment else ""

        doc_table = (
            f"TABLA: {table_name}\n"
            f"Descripcion: Almacena informacion sobre la entidad '{table_name}'. {rows_info}{comment_text}\n"
            f"Clave Primaria: {', '.join(pk_list) if pk_list else 'No definida'}\n"
            f"Columnas y tipos de datos:\n" + "\n".join(cols_desc)
        )
        docs.append({"content": doc_table, "metadata": {"tipo": "tabla", "nombre": table_name}})

        for fk in meta.get("foreign_keys", []):
            col_orig = ", ".join(fk["constrained_columns"])
            tbl_dest = fk["referred_table"]
            col_dest = ", ".join(fk["referred_columns"])
            rel_doc = (
                f"RELACION ENTRE TABLAS:\n"
                f"La tabla '{table_name}' se relaciona con la tabla '{tbl_dest}'.\n"
                f"Clave Foranea: '{table_name}.{col_orig}' referencia a '{tbl_dest}.{col_dest}'.\n"
                f"Tipo de relacion: Cada registro de '{table_name}' apunta a un registro correspondiente en '{tbl_dest}' (muchos a uno)."
            )
            docs.append({"content": rel_doc, "metadata": {"tipo": "relacion", "nombre": f"{table_name}_fk_{tbl_dest}"}})

        for idx in meta.get("indexes", []):
            idx_name = idx.get("name") or f"idx_{table_name}"
            cols = ", ".join(idx.get("column_names", []))
            unique_flag = "unico" if idx.get("unique") else "no unico"
            doc_idx = (
                f"INDICE DE BASE DE DATOS:\n"
                f"Nombre del indice: '{idx_name}' en la tabla '{table_name}'.\n"
                f"Columnas indexadas: [{cols}].\n"
                f"Tipo de indice: {unique_flag}. Sirve para acelerar busquedas y filtros sobre '{cols}'."
            )
            docs.append({"content": doc_idx, "metadata": {"tipo": "indice", "nombre": idx_name}})

    return docs


def generate_single_table_ddl(table_name: str, meta: Dict[str, Any]) -> str:
    """Genera la definición DDL SQL aproximada para una sola tabla."""
    lines = []
    if meta.get("comment"):
        lines.append(f"-- Descripción: {meta['comment']}")
    lines.append(f"CREATE TABLE {table_name} (")
    col_lines = []
    pk_cols = meta.get("primary_key", [])
    for col in meta.get("columns", []):
        pk = " PRIMARY KEY" if col["name"] in pk_cols else ""
        nullable = "" if col.get("nullable", True) else " NOT NULL"
        default = f" DEFAULT {col['default']}" if col.get("default") is not None else ""
        comment = f" -- {col['comment']}" if col.get("comment") else ""
        col_lines.append(f"    {col['name']} {col['type']}{pk}{nullable}{default}{comment}")
    for fk in meta.get("foreign_keys", []):
        col_orig = ", ".join(fk["constrained_columns"])
        col_dest = ", ".join(fk["referred_columns"])
        col_lines.append(f"    FOREIGN KEY ({col_orig}) REFERENCES {fk['referred_table']} ({col_dest})")
    lines.append(",\n".join(col_lines))
    lines.append(");")
    return "\n".join(lines)


def generate_ddl_preview(schema_meta: Dict[str, Any]) -> str:
    """
    Reconstruye un DDL aproximado y solo descriptivo a partir de los
    metadatos introspectados (no es necesariamente ejecutable: no reproduce
    todas las opciones del motor original). Reemplaza al archivo .sql fijo
    que se mostraba antes en la pestana de esquema, que quedaba
    desactualizado en cuanto la base real cambiaba.
    """
    lines = []
    tables = schema_meta.get("tables", {})
    for table_name, meta in tables.items():
        lines.append(f"CREATE TABLE {table_name} (")
        col_lines = []
        for col in meta.get("columns", []):
            pk = " PRIMARY KEY" if col["name"] in meta.get("primary_key", []) else ""
            nullable = "" if col.get("nullable", True) else " NOT NULL"
            col_lines.append(f"    {col['name']} {col['type']}{pk}{nullable}")
        for fk in meta.get("foreign_keys", []):
            col_orig = ", ".join(fk["constrained_columns"])
            col_dest = ", ".join(fk["referred_columns"])
            col_lines.append(f"    FOREIGN KEY ({col_orig}) REFERENCES {fk['referred_table']} ({col_dest})")
        lines.append(",\n".join(col_lines))
        lines.append(");\n")
    return "\n".join(lines)


def _dbml_type(type_str: str) -> str:
    """
    Envuelve el tipo entre comillas dobles si contiene espacios (por ejemplo
    "NUMERIC(10, 2)" o "TIMESTAMP WITHOUT TIME ZONE"): el parser de DBML
    interpreta un tipo sin comillas como un unico token, y falla apenas
    encuentra un espacio dentro de el.
    """
    if " " in type_str and not (type_str.startswith('"') and type_str.endswith('"')):
        return f'"{type_str}"'
    return type_str


def generate_dbml(schema_meta: Dict[str, Any]) -> str:
    """Traduce los metadatos de tablas a DBML (Database Markup Language)."""
    lines = []
    tables = schema_meta.get("tables", {})
    for table_name, meta in tables.items():
        lines.append(f"Table {table_name} {{")
        for col in meta.get("columns", []):
            attrs = []
            if col["name"] in meta.get("primary_key", []):
                attrs.append("pk")
            if not col.get("nullable", True):
                attrs.append("not null")
            attrs_str = f" [{', '.join(attrs)}]" if attrs else ""
            lines.append(f"  {col['name']} {_dbml_type(col['type'])}{attrs_str}")
        if meta.get("comment"):
            safe_comment = meta["comment"].replace("'", "\\'")
            lines.append(f"  Note: '{safe_comment}'")
        lines.append("}\n")

    for table_name, meta in tables.items():
        for fk in meta.get("foreign_keys", []):
            col_orig = fk["constrained_columns"][0] if fk["constrained_columns"] else "?"
            col_dest = fk["referred_columns"][0] if fk["referred_columns"] else "?"
            lines.append(f"Ref: {table_name}.{col_orig} > {fk['referred_table']}.{col_dest}")

    return "\n".join(lines)


def render_dbml_to_svg(dbml_str: str) -> Optional[str]:
    """Renderiza el DBML a SVG llamando a render_dbml.js via Node (opcional)."""
    import subprocess
    import tempfile
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    renderer_script = project_root / "render_dbml.js"
    if not renderer_script.exists():
        return None

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".dbml", delete=False, encoding="utf-8") as f_in:
            f_in.write(dbml_str)
            in_path = f_in.name
        out_path = in_path.replace(".dbml", ".svg")

        res = subprocess.run(
            ["node", str(renderer_script), in_path, out_path],
            capture_output=True, text=True, timeout=30, cwd=str(project_root),
        )
        if res.returncode != 0:
            print(f"[render_dbml_to_svg] Error en proceso node: code={res.returncode}, stderr={res.stderr}, stdout={res.stdout}")
            return None

        svg_path = Path(out_path)
        if svg_path.exists():
            return svg_path.read_text(encoding="utf-8")
        return None
    except Exception as exc:
        print(f"[render_dbml_to_svg] Excepcion: {exc}")
        return None
