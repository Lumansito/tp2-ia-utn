#!/usr/bin/env python3
"""
Script de consola para sembrar la base de datos de demo (15 tablas de
e-commerce con Faker). Deliberadamente NO esta expuesto como un boton en la
app de Streamlit: recrear o tumbar el esquema de una base de datos no puede
ser una accion de un click en una interfaz que ahora lee el esquema
directamente de DATABASE_URL (que puede apuntar a una base real).

Uso:
    python scripts/seed_demo.py --url "sqlite:///data/ecommerce.db" --orders 1500
    python scripts/seed_demo.py --url "$DATABASE_URL" --orders 1500   # o sin --url, usa .env

Pide confirmacion explicita antes de tumbar el esquema (DROP SCHEMA / borrado
de tablas), salvo que se pase --yes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from db_copilot.config import get_engine
from _seed_enterprise_impl import reset_and_seed_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Siembra la base de datos de demo de DB Copilot.")
    parser.add_argument("--url", default=None, help="Connection string. Si se omite, usa DATABASE_URL del .env.")
    parser.add_argument("--orders", type=int, default=1500, help="Cantidad de ordenes a generar (default: 1500).")
    parser.add_argument("--yes", action="store_true", help="No pedir confirmacion antes de tumbar el esquema.")
    args = parser.parse_args()

    engine = get_engine(args.url)
    target = str(engine.url)

    print(f"Esto va a BORRAR y RECREAR el esquema completo en:\n  {target}\n")
    if not args.yes:
        answer = input("Escribi 'si' para confirmar: ").strip().lower()
        if answer not in ("si", "sí", "yes", "y"):
            print("Cancelado.")
            return 1

    reset_and_seed_database(engine, num_orders=args.orders, verbose=True)
    print("\nListo. Base de datos de demo sembrada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
