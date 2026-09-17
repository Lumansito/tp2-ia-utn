"""
Generador de Datos Sintéticos para E-Commerce (PostgreSQL / SQLite).
Utiliza Faker para poblar tablas con volumen realista para consultas y demos.
"""

import random
from datetime import datetime, timedelta
from faker import Faker
from sqlalchemy import text, Engine
from db_copilot.config import get_engine, SQLITE_FALLBACK_URL

fake = Faker("es_ES")


def init_schema(engine: Engine):
    """
    Crea las tablas e índices si no existen.
    Adapta tipos DDL según el dialecto (PostgreSQL usa SERIAL, SQLite usa INTEGER PRIMARY KEY).
    """
    is_sqlite = engine.dialect.name == "sqlite"
    id_col = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"

    ddl = f"""
    CREATE TABLE IF NOT EXISTS customers (
        id {id_col},
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100) NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        city VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS products (
        id {id_col},
        name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        price NUMERIC(10, 2) NOT NULL,
        stock_quantity INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS orders (
        id {id_col},
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS order_items (
        id {id_col},
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL DEFAULT 1,
        unit_price NUMERIC(10, 2) NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
    CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders(order_date);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
    CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
    """

    with engine.begin() as conn:
        for statement in ddl.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def seed_database(
    engine: Engine,
    num_customers: int = 50,
    num_products: int = 25,
    num_orders: int = 1200,
    reset: bool = False,
):
    """
    Puebla la base de datos con clientes, productos, pedidos y detalles de pedido.
    """
    init_schema(engine)

    with engine.begin() as conn:
        # Verificar si ya existen datos
        existing_orders = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0
        if existing_orders > 0 and not reset:
            print(f"[INFO] La base ya contiene {existing_orders} ordenes. Omitiendo seed.")
            return

        if reset:
            conn.execute(text("DELETE FROM order_items"))
            conn.execute(text("DELETE FROM orders"))
            conn.execute(text("DELETE FROM products"))
            conn.execute(text("DELETE FROM customers"))

        # 1. Clientes
        print(f"Poblando {num_customers} clientes...")
        cities = ["Buenos Aires", "Cordoba", "Rosario", "Mendoza", "La Plata", "Mar del Plata", "Salta", "Santa Fe"]
        customer_ids = []
        for _ in range(num_customers):
            first_name = fake.first_name()
            last_name = fake.last_name()
            email = f"{first_name.lower()}.{last_name.lower()}.{fake.unique.random_number(digits=4)}@{fake.free_email_domain()}"
            city = random.choice(cities)
            created_at = fake.date_time_between(start_date="-2y", end_date="-1m")
            res = conn.execute(
                text("INSERT INTO customers (first_name, last_name, email, city, created_at) "
                     "VALUES (:fn, :ln, :email, :city, :cat) RETURNING id" if engine.dialect.name != "sqlite" else
                     "INSERT INTO customers (first_name, last_name, email, city, created_at) VALUES (:fn, :ln, :email, :city, :cat)"),
                {"fn": first_name, "ln": last_name, "email": email, "city": city, "cat": created_at}
            )
            cid = res.scalar() if engine.dialect.name != "sqlite" else conn.execute(text("SELECT last_insert_rowid()")).scalar()
            customer_ids.append(cid)

        # 2. Productos
        print(f"Poblando {num_products} productos...")
        categories = {
            "Electronica": [("Notebook Gamer", 1250.0), ("Monitor 27''", 350.0), ("Teclado Mecanico", 85.0), ("Mouse Inalambrico", 45.0), ("Auriculares Bluetooth", 110.0)],
            "Hogar": [("Cafetera Espresso", 180.0), ("Aspiradora Robot", 290.0), ("Lampara LED Inteligente", 35.0), ("Silla Ergonomica", 220.0)],
            "Ropa": [("Remera de Algodon", 25.0), ("Pantalon Jean", 65.0), ("Campera Termica", 140.0), ("Zapatillas Urbanas", 95.0)],
            "Deportes": [("Pelota de Futbol", 40.0), ("Mancuernas 10kg", 55.0), ("Mat de Yoga", 30.0), ("Bicicleta Mountain Bike", 580.0)],
            "Libros": [("Manual de Inteligencia Artificial", 75.0), ("Diseno de Sistemas Distribuidos", 60.0), ("Patrones de Arquitectura", 50.0)]
        }
        product_list = []
        for cat, items in categories.items():
            for name, price in items:
                stock = random.randint(10, 200)
                res = conn.execute(
                    text("INSERT INTO products (name, category, price, stock_quantity, is_active) "
                         "VALUES (:name, :cat, :price, :stock, :active) RETURNING id" if engine.dialect.name != "sqlite" else
                         "INSERT INTO products (name, category, price, stock_quantity, is_active) VALUES (:name, :cat, :price, :stock, :active)"),
                    {"name": name, "cat": cat, "price": price, "stock": stock, "active": True}
                )
                pid = res.scalar() if engine.dialect.name != "sqlite" else conn.execute(text("SELECT last_insert_rowid()")).scalar()
                product_list.append((pid, price))

        # 3. Órdenes y Detalles de Órdenes
        print(f"Poblando {num_orders} ordenes...")
        statuses = ["pending", "paid", "shipped", "delivered", "cancelled"]
        status_weights = [0.15, 0.25, 0.30, 0.25, 0.05]

        for _ in range(num_orders):
            cust_id = random.choice(customer_ids)
            status = random.choices(statuses, weights=status_weights)[0]
            order_date = fake.date_time_between(start_date="-1y", end_date="now")

            # Crear orden provisional con total 0
            res = conn.execute(
                text("INSERT INTO orders (customer_id, status, total_amount, order_date) "
                     "VALUES (:cid, :status, 0.0, :odate) RETURNING id" if engine.dialect.name != "sqlite" else
                     "INSERT INTO orders (customer_id, status, total_amount, order_date) VALUES (:cid, :status, 0.0, :odate)"),
                {"cid": cust_id, "status": status, "odate": order_date}
            )
            oid = res.scalar() if engine.dialect.name != "sqlite" else conn.execute(text("SELECT last_insert_rowid()")).scalar()

            # Agregar entre 1 y 4 items por orden
            num_items = random.randint(1, 4)
            chosen_products = random.sample(product_list, k=min(num_items, len(product_list)))
            order_total = 0.0

            for pid, unit_price in chosen_products:
                qty = random.randint(1, 3)
                subtotal = qty * unit_price
                order_total += subtotal
                conn.execute(
                    text("INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                         "VALUES (:oid, :pid, :qty, :price)"),
                    {"oid": oid, "pid": pid, "qty": qty, "price": unit_price}
                )

            # Actualizar total calculado
            conn.execute(
                text("UPDATE orders SET total_amount = :total WHERE id = :oid"),
                {"total": round(order_total, 2), "oid": oid}
            )

    print(f"[OK] Base de datos poblada exitosamente ({num_customers} clientes, {len(product_list)} productos, {num_orders} ordenes).")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sembrar base de datos sintética")
    parser.add_argument("--url", default=SQLITE_FALLBACK_URL, help="Connection string de la base")
    parser.add_argument("--reset", action="store_true", help="Limpiar tablas antes de sembrar")
    parser.add_argument("--orders", type=int, default=1200, help="Cantidad de órdenes")
    args = parser.parse_args()

    eng = get_engine(args.url)
    seed_database(eng, num_orders=args.orders, reset=args.reset)
