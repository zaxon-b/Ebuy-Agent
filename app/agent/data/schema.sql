PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'shipped', 'delivered', 'refund_processing',
            'refunded', 'cancelled'
        )
    ),
    items_json TEXT NOT NULL,
    shipping_address TEXT,
    total_amount NUMERIC NOT NULL,
    tracking_number TEXT,
    carrier TEXT,
    logistics_status TEXT,
    logistics_events_json TEXT NOT NULL DEFAULT '[]',
    estimated_delivery TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    price NUMERIC NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0),
    description TEXT,
    specs_json TEXT NOT NULL DEFAULT '{}',
    is_refundable INTEGER NOT NULL DEFAULT 1 CHECK (is_refundable IN (0, 1))
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'approved', 'rejected', 'completed')
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(order_id)
);
