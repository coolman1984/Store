-- Customers keyed by (product, device). Existing rows are trip-orders.
-- Prefer: node scripts/apply-migrations.mjs [--local] <sqlite-path> (guarded).
ALTER TABLE customers ADD COLUMN product TEXT NOT NULL DEFAULT 'trip-orders';
CREATE UNIQUE INDEX IF NOT EXISTS customers_product_device ON customers(product, device);
