-- StockTrack · esquema para PostgreSQL (producción)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','gerente','almacenista','consulta')),
    is_active SMALLINT NOT NULL DEFAULT 1,
    receive_alerts SMALLINT NOT NULL DEFAULT 0,
    must_change_password SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    last_login_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    brand TEXT,
    location TEXT,
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    cost_cents BIGINT NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
    price_cents BIGINT NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    is_active SMALLINT NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_products_active_name ON products (is_active, name);
CREATE INDEX IF NOT EXISTS ix_products_category ON products (category);

CREATE TABLE IF NOT EXISTS stock_movements (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products (id),
    user_id INTEGER REFERENCES users (id),
    kind TEXT NOT NULL CHECK (kind IN ('entrada','salida','ajuste')),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    delta INTEGER NOT NULL,
    stock_before INTEGER NOT NULL CHECK (stock_before >= 0),
    stock_after INTEGER NOT NULL CHECK (stock_after >= 0),
    reference TEXT,
    notes TEXT,
    created_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_movements_product_date ON stock_movements (product_id, created_at);
CREATE INDEX IF NOT EXISTS ix_movements_date ON stock_movements (created_at);

CREATE TABLE IF NOT EXISTS stock_alerts (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products (id),
    status TEXT NOT NULL CHECK (status IN ('abierta','reconocida','resuelta')),
    stock_at_alert INTEGER NOT NULL,
    min_stock_at_alert INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    acknowledged_by INTEGER REFERENCES users (id),
    acknowledged_at TIMESTAMP,
    resolved_at TIMESTAMP,
    email_status TEXT NOT NULL DEFAULT 'pendiente' CHECK (email_status IN ('pendiente','enviado','error','omitido')),
    email_detail TEXT,
    email_sent_at TIMESTAMP
);
-- Una sola alerta vigente (abierta o reconocida) por producto.
CREATE UNIQUE INDEX IF NOT EXISTS ux_alert_open_product ON stock_alerts (product_id) WHERE status IN ('abierta','reconocida');
CREATE INDEX IF NOT EXISTS ix_alerts_status ON stock_alerts (status, created_at);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id),
    alert_id INTEGER REFERENCES stock_alerts (id),
    message TEXT NOT NULL,
    is_read SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications (user_id, is_read);

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    detail TEXT,
    ip TEXT,
    created_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_date ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log (entity, entity_id);
