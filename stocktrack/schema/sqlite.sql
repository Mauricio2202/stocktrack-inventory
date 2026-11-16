-- StockTrack · esquema para SQLite (desarrollo y pruebas)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,                      -- el correo es el identificador de acceso (RF-01)
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','encargado','consulta')),
    is_active SMALLINT NOT NULL DEFAULT 1,
    receive_alerts SMALLINT NOT NULL DEFAULT 0,
    must_change_password SMALLINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active SMALLINT NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_name ON categories (LOWER(name));

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,                        -- código único del producto (RNF-24)
    name TEXT NOT NULL,
    description TEXT,
    category_id INTEGER REFERENCES categories (id),
    brand TEXT,
    location TEXT,
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),   -- retenido por reservas pendientes
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    cost_cents BIGINT NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
    price_cents BIGINT NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    is_active SMALLINT NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (reserved <= stock)
);
CREATE INDEX IF NOT EXISTS ix_products_active_name ON products (is_active, name);
CREATE INDEX IF NOT EXISTS ix_products_category ON products (category_id);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products (id),
    user_id INTEGER REFERENCES users (id),           -- usuario responsable (RNF-26)
    kind TEXT NOT NULL CHECK (kind IN ('compra','venta','devolucion','reserva')),
    status TEXT NOT NULL DEFAULT 'aplicado' CHECK (status IN ('aplicado','pendiente','validado','rechazado')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    delta INTEGER NOT NULL,                          -- variación del stock físico (0 mientras la reserva está pendiente)
    stock_before INTEGER NOT NULL CHECK (stock_before >= 0),
    stock_after INTEGER NOT NULL CHECK (stock_after >= 0),
    reference TEXT,
    notes TEXT,
    parent_id INTEGER REFERENCES stock_movements (id),  -- salida validada -> solicitud de reserva
    request_key TEXT UNIQUE,                         -- evita movimientos duplicados (RNF-15)
    validated_by INTEGER REFERENCES users (id),
    validated_at TEXT,
    validation_note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_movements_product_date ON stock_movements (product_id, created_at);
CREATE INDEX IF NOT EXISTS ix_movements_date ON stock_movements (created_at);
CREATE INDEX IF NOT EXISTS ix_movements_kind_status ON stock_movements (kind, status);

CREATE TABLE IF NOT EXISTS stock_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products (id),
    status TEXT NOT NULL CHECK (status IN ('abierta','atendida','resuelta')),
    stock_at_alert INTEGER NOT NULL,                 -- existencias disponibles al generarse
    min_stock_at_alert INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    attended_by INTEGER REFERENCES users (id),
    attended_at TEXT,
    resolved_at TEXT,
    email_status TEXT NOT NULL DEFAULT 'pendiente' CHECK (email_status IN ('pendiente','enviado','error','omitido')),
    email_detail TEXT,
    email_sent_at TEXT
);
-- Una sola alerta vigente (abierta o atendida) por producto.
CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_open_product ON stock_alerts (product_id) WHERE status IN ('abierta','atendida');
CREATE INDEX IF NOT EXISTS ix_alerts_status ON stock_alerts (status, created_at);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id),
    alert_id INTEGER REFERENCES stock_alerts (id),
    message TEXT NOT NULL,
    is_read SMALLINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications (user_id, is_read);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    actor TEXT,                                      -- correo de quien actuó
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    detail TEXT,
    ip TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_date ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log (entity, entity_id);

-- Registro de reportes emitidos: folio consecutivo + huella SHA-256 del archivo entregado.
CREATE TABLE IF NOT EXISTS report_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio TEXT UNIQUE,
    report_type TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('pdf','xlsx')),
    title TEXT NOT NULL,
    params TEXT,
    row_count INTEGER,
    generated_by INTEGER REFERENCES users (id),
    generated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'generando' CHECK (status IN ('generando','emitido','error')),
    sha256 TEXT,
    size_bytes BIGINT,
    error_detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_report_log_hash ON report_log (sha256);
CREATE INDEX IF NOT EXISTS ix_report_log_date ON report_log (generated_at);
