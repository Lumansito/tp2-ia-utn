#!/usr/bin/env python3
"""
Genera el SQL de esquema + datos de demo (e-commerce chico: categorias,
productos, clientes, ordenes, items de orden y pagos) para precargar el
Postgres de docker-compose.

No se ejecuta en runtime: el resultado de este script queda commiteado en
docker/init/01_schema_and_seed.sql y Postgres lo corre solo, automaticamente,
la primera vez que levanta el contenedor con un volumen de datos vacio (asi
funciona docker-entrypoint-initdb.d en la imagen oficial de postgres).

Para regenerarlo (por ejemplo, para tener otra cantidad de filas):
    pip install faker
    python scripts/generate_demo_sql.py > docker/init/01_schema_and_seed.sql
"""

import random
from datetime import datetime, timedelta

from faker import Faker

SEED = 42
random.seed(SEED)
fake = Faker("es_AR")
Faker.seed(SEED)

N_CATEGORIES = 8
N_PRODUCTS = 60
N_CUSTOMERS = 40
N_ORDERS = 250

ORDER_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"]
PAYMENT_METHODS = ["tarjeta_credito", "tarjeta_debito", "transferencia", "efectivo"]
PAYMENT_STATUSES = ["approved", "pending", "failed", "refunded"]


def esc(value) -> str:
    """Escapa un string para un literal SQL. None -> NULL."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def main() -> None:
    out = []
    out.append("-- Generado por scripts/generate_demo_sql.py (Faker, seed={}).".format(SEED))
    out.append("-- No editar a mano: para cambiar el volumen de datos, regenerar el script.\n")

    # ------------------------------------------------------------------
    # Esquema
    # ------------------------------------------------------------------
    out.append("""
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE
);
COMMENT ON TABLE categories IS 'Rubros o familias de productos del catalogo (ej. Electronica, Hogar).';

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    sku VARCHAR(30) NOT NULL UNIQUE,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    price NUMERIC(10, 2) NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0
);
COMMENT ON TABLE products IS 'Catalogo de productos a la venta.';
COMMENT ON COLUMN products.price IS 'Precio de venta unitario, en pesos argentinos.';
COMMENT ON COLUMN products.stock IS 'Unidades disponibles en stock.';

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    city VARCHAR(100)
);
COMMENT ON TABLE customers IS 'Clientes/compradores registrados.';

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0
);
COMMENT ON TABLE orders IS 'Pedidos/compras realizadas por los clientes.';
COMMENT ON COLUMN orders.status IS 'Estado del pedido: pending, paid, shipped, delivered o cancelled.';
COMMENT ON COLUMN orders.total_amount IS 'Monto total del pedido, calculado a partir de order_items.';

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    line_total NUMERIC(12, 2) NOT NULL
);
COMMENT ON TABLE order_items IS 'Lineas de detalle de cada pedido (que productos y en que cantidad).';

CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    method VARCHAR(30) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    paid_at TIMESTAMP
);
COMMENT ON TABLE payments IS 'Pagos registrados contra un pedido.';
COMMENT ON COLUMN payments.status IS 'Estado del pago: approved, pending, failed o refunded.';

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);
CREATE INDEX idx_payments_order ON payments(order_id);
CREATE INDEX idx_products_category ON products(category_id);
""")

    # ------------------------------------------------------------------
    # Datos: categorias
    # ------------------------------------------------------------------
    category_names = [
        "Electronica", "Hogar y Muebles", "Indumentaria", "Deportes",
        "Libros", "Juguetes", "Jardin", "Herramientas",
    ][:N_CATEGORIES]

    out.append("\n-- Categorias")
    out.append("INSERT INTO categories (id, name, slug) VALUES")
    rows = [
        f"({i+1}, {esc(name)}, {esc(name.lower().replace(' ', '-'))})"
        for i, name in enumerate(category_names)
    ]
    out.append(",\n".join(rows) + ";")

    # ------------------------------------------------------------------
    # Datos: productos
    # ------------------------------------------------------------------
    out.append("\n-- Productos")
    out.append("INSERT INTO products (id, category_id, sku, name, description, price, stock) VALUES")
    product_rows = []
    for i in range(1, N_PRODUCTS + 1):
        category_id = random.randint(1, N_CATEGORIES)
        sku = f"SKU-{i:05d}"
        name = fake.catch_phrase()
        description = fake.sentence(nb_words=10)
        price = round(random.uniform(500, 250000), 2)
        stock = random.randint(0, 200)
        product_rows.append(
            f"({i}, {category_id}, {esc(sku)}, {esc(name)}, {esc(description)}, {price}, {stock})"
        )
    out.append(",\n".join(product_rows) + ";")

    # ------------------------------------------------------------------
    # Datos: clientes
    # ------------------------------------------------------------------
    out.append("\n-- Clientes")
    out.append("INSERT INTO customers (id, first_name, last_name, email, city) VALUES")
    customer_rows = []
    seen_emails = set()
    for i in range(1, N_CUSTOMERS + 1):
        first_name = fake.first_name()
        last_name = fake.last_name()
        base_email = f"{first_name}.{last_name}".lower().replace(" ", "")
        email = f"{base_email}{i}@example.com"
        seen_emails.add(email)
        city = fake.city()
        customer_rows.append(
            f"({i}, {esc(first_name)}, {esc(last_name)}, {esc(email)}, {esc(city)})"
        )
    out.append(",\n".join(customer_rows) + ";")

    # ------------------------------------------------------------------
    # Datos: ordenes + items + pagos
    # ------------------------------------------------------------------
    order_rows = []
    item_rows = []
    payment_rows = []
    item_id = 1
    payment_id = 1
    start_date = datetime.now() - timedelta(days=180)

    for order_id in range(1, N_ORDERS + 1):
        customer_id = random.randint(1, N_CUSTOMERS)
        order_date = start_date + timedelta(
            days=random.randint(0, 180), hours=random.randint(0, 23), minutes=random.randint(0, 59)
        )
        status = random.choices(ORDER_STATUSES, weights=[10, 15, 20, 45, 10])[0]

        n_items = random.randint(1, 4)
        chosen_products = random.sample(range(1, N_PRODUCTS + 1), k=n_items)
        total_amount = 0.0
        for product_id in chosen_products:
            quantity = random.randint(1, 3)
            unit_price = round(random.uniform(500, 250000), 2)
            line_total = round(unit_price * quantity, 2)
            total_amount += line_total
            item_rows.append(
                f"({item_id}, {order_id}, {product_id}, {quantity}, {unit_price}, {line_total})"
            )
            item_id += 1
        total_amount = round(total_amount, 2)

        order_rows.append(
            f"({order_id}, {customer_id}, {esc(order_date.isoformat())}, {esc(status)}, {total_amount})"
        )

        if status != "pending":
            payment_status = "refunded" if status == "cancelled" else random.choices(
                PAYMENT_STATUSES, weights=[85, 5, 5, 5]
            )[0]
            paid_at = order_date + timedelta(hours=random.randint(1, 48))
            payment_rows.append(
                f"({payment_id}, {order_id}, {esc(random.choice(PAYMENT_METHODS))}, "
                f"{total_amount}, {esc(payment_status)}, {esc(paid_at.isoformat())})"
            )
            payment_id += 1

    out.append("\n-- Ordenes")
    out.append("INSERT INTO orders (id, customer_id, order_date, status, total_amount) VALUES")
    out.append(",\n".join(order_rows) + ";")

    out.append("\n-- Items de orden")
    out.append("INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, line_total) VALUES")
    out.append(",\n".join(item_rows) + ";")

    out.append("\n-- Pagos")
    out.append("INSERT INTO payments (id, order_id, method, amount, status, paid_at) VALUES")
    out.append(",\n".join(payment_rows) + ";")

    # ------------------------------------------------------------------
    # Ajustar las secuencias de SERIAL para que sigan despues de los ids fijos
    # ------------------------------------------------------------------
    out.append("\n-- Sincronizar secuencias con los ids insertados a mano")
    for table, col in [
        ("categories", "id"), ("products", "id"), ("customers", "id"),
        ("orders", "id"), ("order_items", "id"), ("payments", "id"),
    ]:
        out.append(
            f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
            f"COALESCE((SELECT MAX({col}) FROM {table}), 1), true);"
        )

    print("\n".join(out))


if __name__ == "__main__":
    main()
