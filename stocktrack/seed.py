"""Datos de demostración: usuarios por rol y un catálogo de tienda de electrónicos."""
from __future__ import annotations

import datetime as dt
import random

from .models import categories, products, stock, users

DEMO_USERS = [
    ("admin", "Ana Garza (Administrador)", "admin@stocktrack.local", "admin", "Admin12345", True),
    ("encargado", "Luis Cantú (Encargado de inventario)", "encargado@stocktrack.local", "encargado", "Encargado12345", True),
    ("consulta", "Sofía Elizondo (Consulta)", "consulta@stocktrack.local", "consulta", "Consulta12345", False),
]

# (categoría, prefijo, marca, nombre, costo MXN, precio MXN, stock, mínimo, unidades vendidas en el periodo)
CATALOG = [
    ("Smartphones", "SMA", "Samsung", "Galaxy S24 128GB", 13200, 17999, 9, 4, 14),
    ("Smartphones", "SMA", "Samsung", "Galaxy A55 256GB", 7900, 10999, 4, 5, 18),
    ("Smartphones", "SMA", "Apple", "iPhone 15 128GB", 14800, 18999, 12, 5, 11),
    ("Smartphones", "SMA", "Motorola", "Moto G84 256GB", 3900, 5499, 22, 6, 9),
    ("Smartphones", "SMA", "Xiaomi", "Redmi Note 13 Pro", 4700, 6499, 15, 6, 12),
    ("Laptops", "LAP", "Lenovo", "IdeaPad Slim 3 15\" Ryzen 5", 9800, 12999, 7, 3, 6),
    ("Laptops", "LAP", "HP", "Pavilion 14 Core i5 16GB", 12400, 15999, 5, 3, 5),
    ("Laptops", "LAP", "Apple", "MacBook Air 13\" M2 8/256", 19500, 23999, 3, 3, 4),
    ("Laptops", "LAP", "ASUS", "Vivobook Go 15 Ryzen 3", 6900, 8999, 10, 3, 4),
    ("Laptops", "LAP", "Dell", "Inspiron 15 Core i7 16GB", 14900, 18999, 6, 2, 3),
    ("Tablets", "TAB", "Apple", "iPad 10a gen 64GB", 6900, 8999, 8, 3, 7),
    ("Tablets", "TAB", "Samsung", "Galaxy Tab A9+ 64GB", 3700, 4999, 14, 4, 5),
    ("Tablets", "TAB", "Lenovo", "Tab M10 Plus 4/128", 3100, 4299, 2, 4, 6),
    ("Televisores", "TEL", "Samsung", "Smart TV 55\" Crystal UHD 4K", 8200, 10999, 6, 2, 5),
    ("Televisores", "TEL", "LG", "Smart TV 50\" UHD ThinQ", 6900, 9299, 5, 2, 4),
    ("Televisores", "TEL", "TCL", "Google TV 43\" Full HD", 3600, 4999, 11, 3, 6),
    ("Televisores", "TEL", "Hisense", "Smart TV 65\" Mini-LED 4K", 11900, 15499, 3, 2, 2),
    ("Audio", "AUD", "Sony", "Audífonos WH-CH720N inalámbricos", 2100, 3199, 18, 5, 9),
    ("Audio", "AUD", "JBL", "Bocina Flip 6 Bluetooth", 1900, 2799, 25, 8, 13),
    ("Audio", "AUD", "Apple", "AirPods 3a generación", 2800, 3899, 9, 5, 10),
    ("Audio", "AUD", "Samsung", "Galaxy Buds2 Pro", 2500, 3499, 7, 4, 5),
    ("Audio", "AUD", "Logitech", "Bocinas Z313 2.1", 750, 1199, 4, 5, 8),
    ("Gaming", "GAM", "Sony", "Consola PlayStation 5 Slim", 8900, 10999, 6, 3, 8),
    ("Gaming", "GAM", "Nintendo", "Switch OLED", 6100, 7699, 8, 3, 6),
    ("Gaming", "GAM", "Microsoft", "Xbox Series S 512GB", 5300, 6799, 5, 2, 4),
    ("Gaming", "GAM", "Logitech", "Mouse G203 Lightsync", 340, 599, 30, 10, 14),
    ("Gaming", "GAM", "Razer", "Teclado BlackWidow V4 X", 2300, 3299, 3, 3, 3),
    ("Accesorios", "ACC", "Anker", "Cargador 20W USB-C", 190, 349, 60, 20, 31),
    ("Accesorios", "ACC", "Anker", "Cable USB-C a USB-C 1.8m", 120, 249, 85, 25, 40),
    ("Accesorios", "ACC", "Samsung", "Memoria microSD 128GB EVO", 210, 399, 40, 15, 22),
    ("Accesorios", "ACC", "Kingston", "Memoria USB 64GB DataTraveler", 110, 199, 55, 15, 18),
    ("Accesorios", "ACC", "Spigen", "Funda para iPhone 15 Ultra Hybrid", 190, 399, 16, 12, 20),
    ("Accesorios", "ACC", "Baseus", "Power bank 20000mAh 65W", 640, 999, 12, 6, 7),
    ("Redes", "RED", "TP-Link", "Router Archer AX23 Wi-Fi 6", 780, 1199, 14, 5, 8),
    ("Redes", "RED", "TP-Link", "Extensor de señal RE305", 420, 699, 9, 4, 5),
    ("Redes", "RED", "Ubiquiti", "Access Point UniFi U6 Lite", 2100, 2899, 6, 3, 2),
    ("Redes", "RED", "D-Link", "Switch 8 puertos Gigabit", 360, 599, 2, 4, 6),
    ("Cómputo", "COM", "Logitech", "Mouse inalámbrico M185", 150, 289, 45, 15, 21),
    ("Cómputo", "COM", "Logitech", "Teclado inalámbrico K270", 340, 549, 20, 8, 9),
    ("Cómputo", "COM", "Samsung", "Monitor 24\" Full HD IPS", 1900, 2699, 8, 4, 5),
    ("Cómputo", "COM", "HP", "Impresora multifuncional Smart Tank 580", 3300, 4499, 5, 3, 4),
    ("Cómputo", "COM", "WD", "Disco duro externo 2TB Elements", 1050, 1599, 13, 5, 7),
    ("Cómputo", "COM", "Kingston", "SSD NV2 1TB NVMe", 890, 1399, 17, 6, 9),
    ("Cámaras", "CAM", "GoPro", "HERO12 Black", 6200, 7999, 4, 2, 3),
    ("Cámaras", "CAM", "Canon", "EOS R50 con lente 18-45mm", 15900, 19499, 2, 2, 1),
    ("Cámaras", "CAM", "TP-Link", "Cámara Tapo C210 Wi-Fi", 420, 699, 26, 8, 12),
    ("Hogar inteligente", "HOG", "Amazon", "Echo Dot 5a gen", 850, 1299, 19, 6, 10),
    ("Hogar inteligente", "HOG", "TP-Link", "Foco inteligente Tapo L530E", 160, 289, 48, 15, 26),
    ("Hogar inteligente", "HOG", "Xiaomi", "Smart Band 8", 560, 899, 3, 6, 11),
    ("Hogar inteligente", "HOG", "Garmin", "Reloj Forerunner 165", 3900, 5199, 4, 2, 2),
]


def seed(db, config: dict, *, force: bool = False) -> str:
    rng = random.Random(2026)
    conn = db.connect()
    try:
        ids: dict[str, int] = {}
        for key, full_name, email, role, password, alerts_on in DEMO_USERS:
            existing = users.get_by_email(conn, email)
            ids[key] = existing["id"] if existing else users.create(
                conn, full_name=full_name, email=email, password=password, role=role,
                receive_alerts=alerts_on, min_password_length=config["PASSWORD_MIN_LENGTH"])
        if products.count_active(conn) and not force:
            return "Ya existen productos; no se cargó el catálogo (usa --force para forzarlo)."

        actor = {"id": ids["admin"], "email": "admin@stocktrack.local", "ip": None}
        cat_ids: dict[str, int] = {}
        counters: dict[str, int] = {}
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        created = 0
        for category, prefix, brand, name, cost, price, current, minimum, sold in CATALOG:
            counters[prefix] = counters.get(prefix, 0) + 1
            brand_code = "".join(ch for ch in brand.upper() if ch.isalnum())[:3]
            sku = f"{prefix}-{brand_code}-{counters[prefix]:03d}"
            if products.get_by_sku(conn, sku):
                continue
            location = f"{prefix[0]}{counters[prefix]:02d}-{rng.randint(1, 4)}"
            if category not in cat_ids:
                row = conn.one("SELECT id FROM categories WHERE LOWER(name) = LOWER(?)", (category,))
                cat_ids[category] = row["id"] if row else categories.create(conn, category, actor)
            data = products.clean_form({
                "sku": sku, "name": name, "category_id": str(cat_ids[category]), "brand": brand, "location": location,
                "min_stock": minimum, "cost": cost, "price": price, "initial_stock": current + sold,
            }, with_initial_stock=True)
            product_id = products.create(conn, data, actor, config["MAX_ACTIVE_RECORDS"])
            # Historial de ventas repartido en los últimos 30 días (fechas retroactivas solo para la demo).
            first = conn.one("SELECT id FROM stock_movements WHERE product_id = ? ORDER BY id LIMIT 1", (product_id,))
            moment = now - dt.timedelta(days=30)
            with conn.transaction():
                conn.execute("UPDATE stock_movements SET created_at = ? WHERE id = ?",
                             (moment.strftime("%Y-%m-%d %H:%M:%S"), first["id"]))
            remaining = sold
            while remaining > 0:
                qty = min(remaining, rng.randint(1, 3))
                result = stock.register_movement(conn, product_id, "venta", qty,
                                                 {"id": ids["encargado"], "email": "encargado@stocktrack.local", "ip": None},
                                                 reference=f"VTA-{rng.randint(1000, 9999)}")
                moment += dt.timedelta(hours=rng.randint(6, 40))
                with conn.transaction():
                    conn.execute("UPDATE stock_movements SET created_at = ? WHERE id = ?",
                                 (min(moment, now).strftime("%Y-%m-%d %H:%M:%S"), result["movement_id"]))
                remaining -= qty
            created += 1
        return f"Datos de demostración cargados: {len(ids)} usuarios y {created} productos."
    finally:
        conn.close()
