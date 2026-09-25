"""
Verifica que la base de demo del docker-compose se haya levantado y cargado bien.

Uso (con el entorno virtual del proyecto activado):
    python scripts/verify_demo_db.py

Que hace:
1. Lee DATABASE_URL desde .env
2. Se conecta a la base
3. Chequea que existan las tablas esperadas
4. Cuenta filas de cada una y las compara contra lo que genera
   scripts/generate_demo_sql.py
5. Imprime un resumen final: OK o los problemas encontrados
"""

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

EXPECTED_COUNTS = {
    "categories": 8,
    "products": 60,
    "customers": 40,
    "orders": 250,
    # order_items y payments tienen cantidades que dependen de datos random,
    # pero con SEED=42 fijo en el generador siempre salen las mismas:
    "order_items": 647,
    "payments": 222,
}


def main() -> int:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: no encontre DATABASE_URL en el .env")
        return 1

    print(f"Conectando a: {database_url.split('@')[-1]}")

    try:
        engine = create_engine(database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        print("ERROR: no me pude conectar a la base.")
        print(f"  Detalle: {exc}")
        print()
        print("Revisa que:")
        print("  - hayas corrido 'docker compose up -d' (o start_app.bat)")
        print("  - el contenedor este healthy: docker compose ps")
        print("  - el DATABASE_URL del .env apunte a localhost:5432")
        return 1

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    problems = []

    missing_tables = set(EXPECTED_COUNTS) - existing_tables
    if missing_tables:
        problems.append(
            f"faltan tablas: {', '.join(sorted(missing_tables))} "
            "(el init script no corrio; probablemente el volumen de datos "
            "ya existia de antes. Probar: docker compose down -v && docker compose up -d)"
        )

    with engine.connect() as conn:
        for table, expected in EXPECTED_COUNTS.items():
            if table not in existing_tables:
                continue
            actual = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            status = "OK" if actual == expected else "DIFERENTE"
            print(f"  {table:15s} filas={actual:<6} esperado={expected:<6} [{status}]")
            if actual != expected:
                problems.append(
                    f"{table}: tiene {actual} filas, se esperaban {expected}"
                )

    print()
    if problems:
        print("Se encontraron problemas:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("Todo OK: la base de demo esta cargada correctamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
