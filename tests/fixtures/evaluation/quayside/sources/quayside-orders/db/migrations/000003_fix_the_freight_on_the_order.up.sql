-- REQ-0001: the freight quoted when the order is placed is fixed on it.
ALTER TABLE orders ADD COLUMN freight_quote_id text;
ALTER TABLE orders ADD COLUMN freight_amount numeric(12, 2);
