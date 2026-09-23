"""
Módulo de Inicialización y Sembrado de Esquema Complejo Empresarial.
Tumba y recrea toda la base de datos de manera agresiva (DROP SCHEMA CASCADE)
y puebla 15 tablas interconectadas con miles de registros consistentes.
"""

import random
from datetime import datetime, timedelta
from faker import Faker
from sqlalchemy import text, Engine
from db_copilot.config import get_engine, SQLITE_FALLBACK_URL

fake = Faker("es_ES")


def drop_and_recreate_schema(engine: Engine):
    """
    Tumba y recrea todo el esquema de la base de datos agresivamente.
    En PostgreSQL: DROP SCHEMA public CASCADE; CREATE SCHEMA public;
    En SQLite: vacía sqlite_master o borra tablas.
    """
    is_postgres = engine.dialect.name == "postgresql"

    with engine.begin() as conn:
        if is_postgres:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
            conn.execute(text("CREATE SCHEMA public;"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC;"))
        else:
            # Para SQLite
            conn.execute(text("PRAGMA foreign_keys = OFF;"))
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).fetchall()
            for t in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{t[0]}";'))
            conn.execute(text("PRAGMA foreign_keys = ON;"))


def create_enterprise_schema(engine: Engine):
    """
    Crea las 15 tablas, claves primarias, foráneas e índices.
    """
    is_sqlite = engine.dialect.name == "sqlite"
    id_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"

    ddl = f"""
    CREATE TABLE IF NOT EXISTS departments (
        id {id_type},
        name VARCHAR(100) NOT NULL UNIQUE,
        code VARCHAR(20) NOT NULL UNIQUE,
        budget NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS employees (
        id {id_type},
        department_id INTEGER NOT NULL REFERENCES departments(id),
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100) NOT NULL,
        email VARCHAR(255) NOT NULL UNIQUE,
        role VARCHAR(80) NOT NULL,
        salary NUMERIC(12, 2) NOT NULL,
        hire_date DATE NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS warehouses (
        id {id_type},
        name VARCHAR(120) NOT NULL UNIQUE,
        code VARCHAR(20) NOT NULL UNIQUE,
        city VARCHAR(100) NOT NULL,
        country VARCHAR(80) NOT NULL DEFAULT 'Argentina',
        capacity_sqm INTEGER NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS suppliers (
        id {id_type},
        company_name VARCHAR(150) NOT NULL,
        contact_name VARCHAR(100) NOT NULL,
        email VARCHAR(255) NOT NULL,
        phone VARCHAR(50),
        country VARCHAR(80) NOT NULL,
        rating NUMERIC(3, 2) DEFAULT 5.00
    );

    CREATE TABLE IF NOT EXISTS categories (
        id {id_type},
        parent_id INTEGER REFERENCES categories(id),
        name VARCHAR(100) NOT NULL UNIQUE,
        slug VARCHAR(120) NOT NULL UNIQUE,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS products (
        id {id_type},
        category_id INTEGER NOT NULL REFERENCES categories(id),
        supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
        sku VARCHAR(50) NOT NULL UNIQUE,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        cost_price NUMERIC(10, 2) NOT NULL,
        sale_price NUMERIC(10, 2) NOT NULL,
        weight_kg NUMERIC(6, 2) DEFAULT 1.00,
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS inventory (
        id {id_type},
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL DEFAULT 0,
        min_threshold INTEGER NOT NULL DEFAULT 10,
        last_restocked_at TIMESTAMP,
        UNIQUE(warehouse_id, product_id)
    );

    CREATE TABLE IF NOT EXISTS customers (
        id {id_type},
        account_type VARCHAR(20) NOT NULL DEFAULT 'retail',
        first_name VARCHAR(100) NOT NULL,
        last_name VARCHAR(100) NOT NULL,
        company_name VARCHAR(150),
        email VARCHAR(255) NOT NULL UNIQUE,
        tax_id VARCHAR(50),
        phone VARCHAR(50),
        credit_limit NUMERIC(12, 2) DEFAULT 50000.00,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS customer_addresses (
        id {id_type},
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        address_type VARCHAR(20) NOT NULL DEFAULT 'shipping',
        street VARCHAR(200) NOT NULL,
        city VARCHAR(100) NOT NULL,
        state VARCHAR(100) NOT NULL,
        postal_code VARCHAR(20) NOT NULL,
        country VARCHAR(80) NOT NULL DEFAULT 'Argentina',
        is_default BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS promotions (
        id {id_type},
        code VARCHAR(50) NOT NULL UNIQUE,
        description VARCHAR(200) NOT NULL,
        discount_pct NUMERIC(5, 2) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS orders (
        id {id_type},
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        assigned_employee_id INTEGER REFERENCES employees(id),
        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
        promotion_id INTEGER REFERENCES promotions(id),
        order_number VARCHAR(50) NOT NULL UNIQUE,
        status VARCHAR(30) NOT NULL DEFAULT 'pending',
        subtotal NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
        discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
        tax_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
        shipping_cost NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
        total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivery_date TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS order_items (
        id {id_type},
        order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL DEFAULT 1,
        unit_price NUMERIC(10, 2) NOT NULL,
        discount_rate NUMERIC(5, 2) DEFAULT 0.00,
        line_total NUMERIC(12, 2) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS payments (
        id {id_type},
        order_id INTEGER NOT NULL REFERENCES orders(id),
        payment_method VARCHAR(40) NOT NULL,
        transaction_reference VARCHAR(100) NOT NULL UNIQUE,
        amount NUMERIC(12, 2) NOT NULL,
        status VARCHAR(30) NOT NULL DEFAULT 'completed',
        paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS shipments (
        id {id_type},
        order_id INTEGER NOT NULL REFERENCES orders(id),
        shipping_address_id INTEGER REFERENCES customer_addresses(id),
        carrier VARCHAR(80) NOT NULL,
        tracking_code VARCHAR(100) NOT NULL UNIQUE,
        status VARCHAR(30) NOT NULL DEFAULT 'preparing',
        shipped_at TIMESTAMP,
        delivered_at TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS product_reviews (
        id {id_type},
        product_id INTEGER NOT NULL REFERENCES products(id),
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_emp_dept ON employees(department_id);
    CREATE INDEX IF NOT EXISTS idx_prod_cat ON products(category_id);
    CREATE INDEX IF NOT EXISTS idx_prod_sup ON products(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_inv_wh ON inventory(warehouse_id);
    CREATE INDEX IF NOT EXISTS idx_inv_prod ON inventory(product_id);
    CREATE INDEX IF NOT EXISTS idx_ord_cust ON orders(customer_id);
    CREATE INDEX IF NOT EXISTS idx_ord_date ON orders(order_date);
    CREATE INDEX IF NOT EXISTS idx_ord_status ON orders(status);
    CREATE INDEX IF NOT EXISTS idx_item_ord ON order_items(order_id);
    CREATE INDEX IF NOT EXISTS idx_pay_ord ON payments(order_id);
    CREATE INDEX IF NOT EXISTS idx_ship_ord ON shipments(order_id);
    """

    with engine.begin() as conn:
        for stmt in ddl.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))


def populate_enterprise_data(engine: Engine, num_orders: int = 1500, verbose: bool = True):
    """
    Puebla datos masivos y consistentes para las 15 tablas.
    """
    is_postgres = engine.dialect.name == "postgresql"

    with engine.begin() as conn:
        # Helper para insertar y retornar IDs
        def insert_get_ids(table_name: str, rows: list, id_col: str = "id") -> list:
            if not rows:
                return []
            ids = []
            if is_postgres:
                for r in rows:
                    cols = ", ".join(r.keys())
                    params = ", ".join([f":{k}" for k in r.keys()])
                    res = conn.execute(text(f"INSERT INTO {table_name} ({cols}) VALUES ({params}) RETURNING {id_col}"), r)
                    ids.append(res.scalar())
            else:
                for r in rows:
                    cols = ", ".join(r.keys())
                    params = ", ".join([f":{k}" for k in r.keys()])
                    conn.execute(text(f"INSERT INTO {table_name} ({cols}) VALUES ({params})"), r)
                    last_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
                    ids.append(last_id)
            return ids

        if verbose:
            print("Poblando departamentos y empleados...")
        # 1. Departments
        depts_data = [
            {"name": "Ventas B2B", "code": "VENT-B2B", "budget": 850000.0},
            {"name": "E-Commerce & Retail", "code": "VENT-RET", "budget": 1200000.0},
            {"name": "Logistica y Abastecimiento", "code": "LOG-OPS", "budget": 650000.0},
            {"name": "Atencion al Cliente", "code": "CS-SUPP", "budget": 320000.0},
            {"name": "Marketing & Crecimiento", "code": "MKT-GROWTH", "budget": 450000.0},
            {"name": "Finanzas y Cobranzas", "code": "FIN-OPS", "budget": 390000.0}
        ]
        dept_ids = insert_get_ids("departments", depts_data)

        # 2. Employees
        employees_data = []
        roles = ["Account Executive", "Supervisor de Logistica", "Representante de Soporte", "Gerente de Producto", "Analista Financiero"]
        for _ in range(25):
            employees_data.append({
                "department_id": random.choice(dept_ids),
                "first_name": fake.first_name(),
                "last_name": fake.last_name(),
                "email": fake.unique.email(),
                "role": random.choice(roles),
                "salary": round(random.uniform(900.0, 3500.0), 2),
                "hire_date": fake.date_between(start_date="-4y", end_date="-2m"),
                "is_active": True
            })
        employee_ids = insert_get_ids("employees", employees_data)

        # 3. Warehouses
        if verbose:
            print("Poblando almacenes y proveedores...")
        warehouses_data = [
            {"name": "Hub Central Buenos Aires", "code": "WH-BUE", "city": "Buenos Aires", "country": "Argentina", "capacity_sqm": 8500, "is_active": True},
            {"name": "Centro de Distribucion Cordoba", "code": "WH-COR", "city": "Cordoba", "country": "Argentina", "capacity_sqm": 4200, "is_active": True},
            {"name": "Deposito Regional Rosario", "code": "WH-ROS", "city": "Rosario", "country": "Argentina", "capacity_sqm": 3100, "is_active": True},
            {"name": "Hub Logistico Cuyo Mendoza", "code": "WH-MDZ", "city": "Mendoza", "country": "Argentina", "capacity_sqm": 2600, "is_active": True}
        ]
        warehouse_ids = insert_get_ids("warehouses", warehouses_data)

        # 4. Suppliers
        suppliers_data = []
        countries = ["Argentina", "Brasil", "China", "Estados Unidos", "Alemania", "Chile"]
        for _ in range(15):
            suppliers_data.append({
                "company_name": fake.company(),
                "contact_name": fake.name(),
                "email": fake.company_email(),
                "phone": fake.phone_number()[:40],
                "country": random.choice(countries),
                "rating": round(random.uniform(3.5, 5.0), 2)
            })
        supplier_ids = insert_get_ids("suppliers", suppliers_data)

        # 5. Categories (Jerárquicas)
        if verbose:
            print("Poblando arbol de categorias y productos...")
        parent_cats = [
            {"parent_id": None, "name": "Tecnologia", "slug": "tecnologia", "description": "Dispositivos electronicos e informatica"},
            {"parent_id": None, "name": "Hogar y Muebles", "slug": "hogar", "description": "Mobiliario y confort para el hogar"},
            {"parent_id": None, "name": "Equipamiento Industrial", "slug": "industrial", "description": "Maquinarias y herramientas pesadas"},
            {"parent_id": None, "name": "Deportes y Fitness", "slug": "deportes", "description": "Articulos deportivos y outdoor"}
        ]
        parent_cat_ids = insert_get_ids("categories", parent_cats)

        sub_cats = [
            {"parent_id": parent_cat_ids[0], "name": "Laptops y Servidores", "slug": "laptops-servidores", "description": "Equipos de computo"},
            {"parent_id": parent_cat_ids[0], "name": "Redes y Conectividad", "slug": "redes", "description": "Routers, switches y cableado"},
            {"parent_id": parent_cat_ids[1], "name": "Oficina Ergonomica", "slug": "oficina-ergonomica", "description": "Escritorios y sillas"},
            {"parent_id": parent_cat_ids[2], "name": "Herramientas de Precision", "slug": "herramientas", "description": "Medidores y taladros industriales"},
            {"parent_id": parent_cat_ids[3], "name": "Musculacion y Cardio", "slug": "fitness", "description": "Equipamiento de gimnasio"}
        ]
        sub_cat_ids = insert_get_ids("categories", sub_cats)
        all_cat_ids = parent_cat_ids + sub_cat_ids

        # 6. Products
        products_data = []
        prod_names = [
            ("Server Rack 42U Xeon Enterprise", 2800.0, 4200.0),
            ("Notebook ThinkStation Pro 64GB", 1850.0, 2699.0),
            ("Switch Administrable 48 Puertos PoE", 620.0, 950.0),
            ("Router Industrial 5G redundante", 430.0, 720.0),
            ("Silla Ergonomica Herman Miller Type", 380.0, 650.0),
            ("Escritorio Elevable Electrico Dual Motor", 410.0, 690.0),
            ("Generador Trifasico Industrial 15KVA", 1900.0, 3100.0),
            ("Torno Mecanico de Precision Digital", 1400.0, 2400.0),
            ("Cinta de Correr Profesional 4HP", 850.0, 1450.0),
            ("Estacion Multigimnasio 80kg", 520.0, 890.0),
            ("Monitor Curvo 49 Pulgadas DQHD", 780.0, 1250.0),
            ("Camara Termografica de Inspeccion", 950.0, 1600.0),
            ("Impresora Laser Multifuncion Departamental", 560.0, 890.0),
            ("UPS Online Doble Conversion 6KVA", 1100.0, 1850.0),
            ("Kit Sensores IoT Telemetria Industrial", 320.0, 580.0)
        ]
        for idx, (pname, cost, sale) in enumerate(prod_names):
            products_data.append({
                "category_id": random.choice(all_cat_ids),
                "supplier_id": random.choice(supplier_ids),
                "sku": f"PRD-SKU-{idx+1:04d}",
                "name": pname,
                "description": f"Especificacion tecnica de {pname} de alta gama empresarial.",
                "cost_price": cost,
                "sale_price": sale,
                "weight_kg": round(random.uniform(1.5, 45.0), 2),
                "is_active": True
            })
        product_ids = insert_get_ids("products", products_data)

        # 7. Inventory (N-M)
        if verbose:
            print("Poblando inventarios en almacenes...")
        inv_data = []
        for pid in product_ids:
            for wid in warehouse_ids:
                inv_data.append({
                    "warehouse_id": wid,
                    "product_id": pid,
                    "quantity": random.randint(15, 300),
                    "min_threshold": 20,
                    "last_restocked_at": fake.date_time_between(start_date="-3m", end_date="now")
                })
        insert_get_ids("inventory", inv_data)

        # 8. Customers & Addresses
        if verbose:
            print("Poblando clientes y direcciones...")
        customers_data = []
        account_types = ["retail", "wholesale", "vip"]
        weights = [0.6, 0.3, 0.1]
        for i in range(80):
            fn = fake.first_name()
            ln = fake.last_name()
            acc = random.choices(account_types, weights=weights)[0]
            comp = fake.company() if acc != "retail" else None
            customers_data.append({
                "account_type": acc,
                "first_name": fn,
                "last_name": ln,
                "company_name": comp,
                "email": f"{fn.lower()}.{ln.lower()}.{i+10}@{fake.free_email_domain()}",
                "tax_id": f"30-{random.randint(50000000, 90000000)}-{random.randint(0, 9)}",
                "phone": fake.phone_number()[:40],
                "credit_limit": 50000.0 if acc == "retail" else 500000.0,
                "is_active": True,
                "created_at": fake.date_time_between(start_date="-2y", end_date="-1m")
            })
        customer_ids = insert_get_ids("customers", customers_data)

        addresses_data = []
        cities = ["Buenos Aires", "Cordoba", "Rosario", "Mendoza", "La Plata", "Mar del Plata", "San Miguel de Tucuman"]
        for cid in customer_ids:
            for ad_type in ["shipping", "billing"]:
                addresses_data.append({
                    "customer_id": cid,
                    "address_type": ad_type,
                    "street": fake.street_address(),
                    "city": random.choice(cities),
                    "state": "Provincia Central",
                    "postal_code": str(random.randint(1000, 9000)),
                    "country": "Argentina",
                    "is_default": ad_type == "shipping"
                })
        address_ids = insert_get_ids("customer_addresses", addresses_data)

        # 9. Promotions
        promos_data = [
            {"code": "CYBER-10", "description": "Descuento 10% CyberWeek", "discount_pct": 10.0, "start_date": fake.date_between(start_date="-1y", end_date="-6m"), "end_date": fake.date_between(start_date="-6m", end_date="+3m"), "is_active": True},
            {"code": "EMPRESAS-15", "description": "Descuento B2B Mayorista", "discount_pct": 15.0, "start_date": fake.date_between(start_date="-1y", end_date="-6m"), "end_date": fake.date_between(start_date="+1m", end_date="+6m"), "is_active": True},
            {"code": "VIP-EXP", "description": "Beneficio Clientes VIP", "discount_pct": 20.0, "start_date": fake.date_between(start_date="-1y", end_date="-1m"), "end_date": fake.date_between(start_date="+2m", end_date="+8m"), "is_active": True}
        ]
        promo_ids = insert_get_ids("promotions", promos_data)

        # 10. Orders, Order Items, Payments, Shipments
        if verbose:
            print(f"Poblando {num_orders} ordenes con items, pagos y envios en cascada...")

        statuses = ["paid", "processing", "shipped", "delivered", "cancelled"]
        st_weights = [0.15, 0.15, 0.25, 0.40, 0.05]
        carriers = ["Andreani", "DHL Express", "FedEx", "Correo Argentino"]
        pay_methods = ["credit_card", "bank_transfer", "mercadopago", "cash"]

        # Cache de productos para precios
        prod_map = {pid: prod_names[i % len(prod_names)][2] for i, pid in enumerate(product_ids)}

        for o_idx in range(num_orders):
            cid = random.choice(customer_ids)
            eid = random.choice(employee_ids)
            wid = random.choice(warehouse_ids)
            promo_id = random.choice(promo_ids) if random.random() < 0.3 else None
            status = random.choices(statuses, weights=st_weights)[0]
            order_date = fake.date_time_between(start_date="-18m", end_date="now")
            delivery_date = order_date + timedelta(days=random.randint(2, 7)) if status == "delivered" else None
            order_num = f"ORD-2025-{o_idx+1:06d}"

            # Insertar orden provisional
            order_record = {
                "customer_id": cid,
                "assigned_employee_id": eid,
                "warehouse_id": wid,
                "promotion_id": promo_id,
                "order_number": order_num,
                "status": status,
                "subtotal": 0.0,
                "discount_amount": 0.0,
                "tax_amount": 0.0,
                "shipping_cost": 25.0,
                "total_amount": 0.0,
                "order_date": order_date,
                "delivery_date": delivery_date
            }
            oid = insert_get_ids("orders", [order_record])[0]

            # Ítems
            items_count = random.randint(1, 5)
            chosen_pids = random.sample(product_ids, k=min(items_count, len(product_ids)))
            subtotal = 0.0

            for pid in chosen_pids:
                qty = random.randint(1, 4)
                uprice = prod_map[pid]
                ltotal = qty * uprice
                subtotal += ltotal
                conn.execute(
                    text("INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount_rate, line_total) "
                         "VALUES (:oid, :pid, :qty, :uprice, 0.0, :ltotal)"),
                    {"oid": oid, "pid": pid, "qty": qty, "uprice": uprice, "ltotal": ltotal}
                )

            discount = round(subtotal * 0.15, 2) if promo_id else 0.0
            tax = round((subtotal - discount) * 0.21, 2)
            total = round(subtotal - discount + tax + 25.0, 2)

            # Actualizar totales
            conn.execute(
                text("UPDATE orders SET subtotal = :sub, discount_amount = :disc, tax_amount = :tax, total_amount = :tot WHERE id = :oid"),
                {"sub": subtotal, "disc": discount, "tax": tax, "tot": total, "oid": oid}
            )

            # Pago
            if status != "cancelled":
                conn.execute(
                    text("INSERT INTO payments (order_id, payment_method, transaction_reference, amount, status, paid_at) "
                         "VALUES (:oid, :pm, :tr, :amt, 'completed', :pdate)"),
                    {
                        "oid": oid,
                        "pm": random.choice(pay_methods),
                        "tr": f"TRX-{uuid_gen()}",
                        "amt": total,
                        "pdate": order_date
                    }
                )

            # Envío
            if status in ("shipped", "delivered"):
                conn.execute(
                    text("INSERT INTO shipments (order_id, shipping_address_id, carrier, tracking_code, status, shipped_at, delivered_at) "
                         "VALUES (:oid, :aid, :carr, :tcode, :sh_st, :sh_date, :del_date)"),
                    {
                        "oid": oid,
                        "aid": random.choice(address_ids),
                        "carr": random.choice(carriers),
                        "tcode": f"TRK-{uuid_gen()}",
                        "sh_st": "delivered" if status == "delivered" else "in_transit",
                        "sh_date": order_date + timedelta(days=1),
                        "del_date": delivery_date
                    }
                )

        # 11. Product Reviews
        if verbose:
            print("Poblando resenas y opiniones de productos...")
        comments = [
            "Excelente rendimiento para trabajo pesado, muy recomendable.",
            "Cumple con lo esperado, envio rapido y buena calidad.",
            "Buen producto, aunque la documentacion podria mejorar.",
            "Robusto y confiable para entorno empresarial 24/7.",
            "Muy conforme con el soporte del fabricante y la garantia."
        ]
        for _ in range(300):
            conn.execute(
                text("INSERT INTO product_reviews (product_id, customer_id, rating, comment, created_at) "
                     "VALUES (:pid, :cid, :rt, :cm, :cat)"),
                {
                    "pid": random.choice(product_ids),
                    "cid": random.choice(customer_ids),
                    "rt": random.randint(3, 5),
                    "cm": random.choice(comments),
                    "cat": fake.date_time_between(start_date="-1y", end_date="now")
                }
            )

    if verbose:
        print("[OK] Base de datos empresarial recreada y poblada exitosamente con 15 tablas.")


def uuid_gen():
    import uuid
    return str(uuid.uuid4())[:12].upper()


def reset_and_seed_database(engine: Engine, num_orders: int = 1500, verbose: bool = True):
    """
    Función principal de ejecución: tumba el esquema, recrea las tablas y puebla todos los datos.
    """
    if verbose:
        print(f"--- [RESET AGRESIVO] Tumbando base de datos ({engine.dialect.name})... ---")
    drop_and_recreate_schema(engine)
    if verbose:
        print("--- [DDL] Recreando 15 tablas e indices... ---")
    create_enterprise_schema(engine)
    if verbose:
        print("--- [SEED] Insertando datos masivos... ---")
    populate_enterprise_data(engine, num_orders=num_orders, verbose=verbose)


if __name__ == "__main__":
    eng = get_engine()
    reset_and_seed_database(eng, num_orders=500)
