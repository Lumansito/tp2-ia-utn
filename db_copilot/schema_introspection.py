"""
Módulo de Introspección de Esquema y Generación de Documentos NLP.
Extrae metadatos del catálogo relacional usando SQLAlchemy inspect(),
o a partir de archivos DDL / JSON provistos por el usuario,
y genera documentos en lenguaje natural para la base de conocimiento RAG.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from sqlalchemy import inspect, text, Engine


def introspect_database(engine: Engine) -> Dict[str, Any]:
    """
    Inspecciona la base de datos conectada mediante SQLAlchemy inspect().
    Devuelve un diccionario estructurado con metadatos del motor, tablas,
    columnas, tipos, claves primarias, claves foráneas e índices.
    """
    inspector = inspect(engine)
    dialect_name = engine.dialect.name
    
    # Obtener versión o información del servidor
    server_version = "Desconocida"
    try:
        with engine.connect() as conn:
            if dialect_name == "postgresql":
                ver = conn.execute(text("SELECT version();")).scalar()
                server_version = ver.split()[0] + " " + ver.split()[1] if ver else "PostgreSQL"
            elif dialect_name == "sqlite":
                ver = conn.execute(text("SELECT sqlite_version();")).scalar()
                server_version = f"SQLite {ver}"
    except Exception:
        server_version = f"{dialect_name.capitalize()}"

    table_names = inspector.get_table_names()
    tables_meta = {}

    for table in table_names:
        columns = inspector.get_columns(table)
        pk_constraint = inspector.get_pk_constraint(table)
        fks = inspector.get_foreign_keys(table)
        indexes = inspector.get_indexes(table)
        
        # Cantidad aproximada de filas
        row_count = None
        try:
            with engine.connect() as conn:
                row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"' if dialect_name == "postgresql" else f'SELECT COUNT(*) FROM {table}')).scalar()
        except Exception:
            row_count = None

        tables_meta[table] = {
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default", "")) if col.get("default") is not None else None,
                }
                for col in columns
            ],
            "primary_key": pk_constraint.get("constrained_columns", []),
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
        "tables": tables_meta,
    }


def parse_json_schema(json_data: str | dict) -> Dict[str, Any]:
    """
    Carga metadatos de esquema desde un formato JSON personalizado.
    Permite configurar el esquema manualmente sin requerir introspección directa.
    """
    data = json.loads(json_data) if isinstance(json_data, str) else json_data
    return {
        "engine": data.get("engine", "postgresql"),
        "version": data.get("version", "PostgreSQL"),
        "tables": data.get("tables", {}),
    }


def parse_ddl_schema(ddl_sql: str, dialect_name: str = "postgresql") -> Dict[str, Any]:
    """
    Parsea sentencias DDL (CREATE TABLE) básicas para extraer tablas y columnas
    cuando se suministra un archivo .sql de esquema.
    """
    tables = {}
    table_blocks = re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s*\((.*?)\);", ddl_sql, re.DOTALL | re.IGNORECASE)
    
    for table_name, body in table_blocks:
        columns = []
        pks = []
        fks = []
        
        lines = [line.strip() for line in body.split(",") if line.strip()]
        for line in lines:
            line_upper = line.upper()
            if line_upper.startswith("PRIMARY KEY"):
                m = re.search(r"PRIMARY\s+KEY\s*\((.*?)\)", line, re.IGNORECASE)
                if m:
                    pks = [c.strip().strip('"') for c in m.group(1).split(",")]
            elif "REFERENCES" in line_upper:
                m = re.search(r"([a-zA-Z0-9_]+).*?REFERENCES\s+([a-zA-Z0-9_]+)\s*\(([a-zA-Z0-9_]+)\)", line, re.IGNORECASE)
                if m:
                    fks.append({
                        "constrained_columns": [m.group(1)],
                        "referred_table": m.group(2),
                        "referred_columns": [m.group(3)],
                    })
            elif not line_upper.startswith("CONSTRAINT") and not line_upper.startswith("KEY"):
                parts = line.split()
                if len(parts) >= 2:
                    col_name = parts[0].strip('"')
                    col_type = parts[1]
                    is_pk = "PRIMARY KEY" in line_upper
                    if is_pk:
                        pks.append(col_name)
                    columns.append({
                        "name": col_name,
                        "type": col_type,
                        "nullable": "NOT NULL" not in line_upper,
                        "default": None,
                    })
                    
        tables[table_name] = {
            "columns": columns,
            "primary_key": pks,
            "foreign_keys": fks,
            "indexes": [],
            "row_count": None,
        }

    return {
        "engine": dialect_name,
        "version": f"{dialect_name.capitalize()} (Esquema DDL estático)",
        "tables": tables,
    }


def generate_natural_language_docs(schema_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convierte los metadatos estructurados en documentos de texto en lenguaje natural
    diseñados para ser vectorizados y consultados vía RAG.
    
    Genera:
    - 1 documento del motor y dialecto.
    - 1 documento por cada tabla (columnas, tipos, PK, filas).
    - 1 documento por cada relación de clave foránea (FK).
    - 1 documento por cada índice relevante.
    """
    docs = []
    engine_name = schema_meta.get("engine", "postgresql")
    version = schema_meta.get("version", "N/A")
    tables = schema_meta.get("tables", {})

    # 1. Documento del Motor de Base de Datos
    engine_notes = {
        "postgresql": "PostgreSQL es un motor relacional avanzado con soporte para tipos estrictos, JSONB, índices B-Tree/GIN/GiST, funciones de ventana, transacciones ACID completas y aislamiento serializable.",
        "sqlite": "SQLite es un motor relacional ligero basado en archivos, adecuado para prototipos y pruebas locales. Tipado dinámico con afinidad de tipos.",
    }
    engine_note = engine_notes.get(engine_name.lower(), f"Motor de base de datos relacional compatible con SQL estándar.")

    doc_engine = (
        f"MOTOR DE BASE DE DATOS Y ENTORNO:\n"
        f"Motor configurado: {engine_name.upper()}\n"
        f"Versión: {version}\n"
        f"Dialecto SQLAlchemy: {engine_name}\n"
        f"Características y particularidades: {engine_note}\n"
        f"Tablas disponibles en la base de datos: {', '.join(tables.keys())}."
    )
    docs.append({
        "content": doc_engine,
        "metadata": {"tipo": "motor", "nombre": engine_name}
    })

    # 2. Documentos por Tabla
    for table_name, meta in tables.items():
        cols_desc = []
        pk_list = meta.get("primary_key", [])
        for col in meta.get("columns", []):
            pk_flag = " [CLAVE PRIMARIA (PK)]" if col["name"] in pk_list else ""
            null_flag = "opcional (NULL)" if col.get("nullable") else "obligatorio (NOT NULL)"
            cols_desc.append(f"  - Columna '{col['name']}': Tipo {col['type']}, {null_flag}{pk_flag}")

        synonyms_map = {
            "customers": "clientes, compradores, usuarios registrados, cuentas de cliente. NOTA IMPORTANTE: Para el nombre usar 'first_name' y 'last_name' o 'company_name'; la tabla NO tiene una columna 'name'.",
            "orders": "órdenes, pedidos, compras realizadas, transacciones de venta.",
            "order_items": "ítems del pedido, detalle de la orden, líneas de compra, productos comprados.",
            "products": "productos, artículos del catálogo, mercadería a la venta.",
            "categories": "categorías de productos, rubros, familias.",
            "inventory": "stock, existencias de inventario por almacén, disponibilidad.",
            "warehouses": "almacenes, depósitos físicos, centros de distribución.",
            "suppliers": "proveedores, distribuidores, fabricantes.",
            "employees": "empleados, personal, staff, trabajadores.",
            "departments": "departamentos, áreas, sectores de la empresa.",
            "payments": "pagos recibidos, transacciones de cobro, facturación.",
            "shipments": "envíos, despachos logísticos, entregas, seguimiento.",
            "promotions": "promociones, cupones de descuento, ofertas.",
            "product_reviews": "reseñas, calificaciones de productos, opiniones.",
            "customer_addresses": "direcciones de clientes, domicilios de entrega."
        }
        synonym_text = f"\nConceptos y términos en español: {synonyms_map.get(table_name, '')}"

        rows_info = f"Contiene aproximadamente {meta['row_count']} registros." if meta.get("row_count") is not None else "Cantidad de filas variable."

        doc_table = (
            f"TABLA: {table_name}\n"
            f"Descripción: Almacena información sobre la entidad '{table_name}'. {rows_info}{synonym_text}\n"
            f"Clave Primaria: {', '.join(pk_list) if pk_list else 'No definida'}\n"
            f"Columnas y tipos de datos:\n" + "\n".join(cols_desc)
        )
        docs.append({
            "content": doc_table,
            "metadata": {"tipo": "tabla", "nombre": table_name}
        })

        # 3. Documentos por Relación (Foreign Key)
        for fk in meta.get("foreign_keys", []):
            col_orig = ", ".join(fk["constrained_columns"])
            tbl_dest = fk["referred_table"]
            col_dest = ", ".join(fk["referred_columns"])
            rel_doc = (
                f"RELACIÓN ENTRE TABLAS:\n"
                f"La tabla '{table_name}' se relaciona con la tabla '{tbl_dest}'.\n"
                f"Clave Foránea: '{table_name}.{col_orig}' referencia a '{tbl_dest}.{col_dest}'.\n"
                f"Tipo de relación: Cada registro de '{table_name}' apunta a un registro correspondiente en '{tbl_dest}' (relación de muchos a uno)."
            )
            docs.append({
                "content": rel_doc,
                "metadata": {"tipo": "relacion", "nombre": f"{table_name}_fk_{tbl_dest}"}
            })

        # 4. Documentos por Índice
        for idx in meta.get("indexes", []):
            idx_name = idx.get("name") or f"idx_{table_name}"
            cols = ", ".join(idx.get("column_names", []))
            unique_flag = "único" if idx.get("unique") else "no único"
            doc_idx = (
                f"ÍNDICE DE BASE DE DATOS:\n"
                f"Nombre del índice: '{idx_name}' en la tabla '{table_name}'.\n"
                f"Columnas indexadas: [{cols}].\n"
                f"Tipo de índice: {unique_flag}. Sirve para acelerar búsquedas y filtros sobre '{cols}'."
            )
            docs.append({
                "content": doc_idx,
                "metadata": {"tipo": "indice", "nombre": idx_name}
            })

    return docs


def generate_dbml(schema_meta: Dict[str, Any]) -> str:
    """
    Genera la especificación DBML (Database Markup Language) a partir del esquema relacional.
    Estándar moderno para diagramas DER compatible con dbdiagram.io.
    """
    tables = schema_meta.get("tables", {})
    if not tables:
        return "// Base de datos sin tablas creadas aún.\n"

    lines = [
        "// ========================================================",
        "// Esquema Relacional en formato DBML (Database Markup Language)",
        f"// Motor: {schema_meta.get('engine', 'PostgreSQL').upper()} - Versión: {schema_meta.get('version', 'N/A')}",
        "// ========================================================\n"
    ]

    # 1. Definición de Tablas
    for table_name, meta in tables.items():
        pks = set(meta.get("primary_key", []))
        lines.append(f"Table {table_name} {{")
        for col in meta.get("columns", []):
            cname = col["name"]
            raw_type = col["type"].lower()
            # Mapear tipos a equivalentes canónicos de DBML
            if "int" in raw_type or "serial" in raw_type:
                dbml_type = "integer"
            elif "numeric" in raw_type or "decimal" in raw_type or "real" in raw_type:
                dbml_type = "numeric"
            elif "bool" in raw_type:
                dbml_type = "boolean"
            elif "date" in raw_type or "time" in raw_type:
                dbml_type = "timestamp"
            elif "text" in raw_type or "char" in raw_type:
                dbml_type = "varchar"
            else:
                dbml_type = raw_type.split("(")[0]

            settings = []
            if cname in pks:
                settings.append("pk")
                if "serial" in raw_type or "auto" in raw_type:
                    settings.append("increment")
            if not col.get("nullable", True) and cname not in pks:
                settings.append("not null")

            set_str = f" [{', '.join(settings)}]" if settings else ""
            lines.append(f"  {cname} {dbml_type}{set_str}")
        lines.append("}\n")

    # 2. Relaciones (Refs)
    lines.append("// Relaciones de Claves Foráneas (Foreign Keys)")
    rel_seen = set()
    for table_name, meta in tables.items():
        for fk in meta.get("foreign_keys", []):
            dest_table = fk.get("referred_table")
            if dest_table and dest_table in tables:
                orig_col = fk.get("constrained_columns", ["id"])[0]
                dest_col = fk.get("referred_columns", ["id"])[0]
                ref_key = f"{table_name}.{orig_col} > {dest_table}.{dest_col}"
                if ref_key not in rel_seen:
                    rel_seen.add(ref_key)
                    lines.append(f"Ref: {table_name}.{orig_col} > {dest_table}.{dest_col}")

    return "\n".join(lines)


def render_dbml_to_svg(dbml_str: str) -> Optional[str]:
    """
    Renderiza código DBML a una imagen SVG vectorial nítida usando Node.js y @softwaretechnik/dbml-renderer.
    """
    import subprocess
    import tempfile
    from pathlib import Path

    base_dir = Path(__file__).resolve().parent.parent
    renderer_script = base_dir / "render_dbml.js"
    if not renderer_script.exists():
        return None

    in_path = None
    out_path = None
    try:
        f_in = tempfile.NamedTemporaryFile(suffix=".dbml", mode="w", encoding="utf-8", delete=False)
        f_in.write(dbml_str)
        in_path = f_in.name
        f_in.close()

        out_path = in_path.replace(".dbml", ".svg")

        res = subprocess.run(
            ["node", str(renderer_script), in_path, out_path],
            capture_output=True,
            text=True,
            timeout=25,
            cwd=str(base_dir),
            shell=True,
        )

        if res.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as svg_file:
                content = svg_file.read()
            return content
        else:
            print(f"[render_dbml_to_svg] Error en proceso node: code={res.returncode}, stderr={res.stderr}, stdout={res.stdout}")
            return None
    except Exception as exc:
        print(f"[render_dbml_to_svg] Excepción capturada: {exc}")
        return None
    finally:
        try:
            if in_path and os.path.exists(in_path):
                os.remove(in_path)
            if out_path and os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass

    return None


