-- The orders a customer placed.
CREATE TABLE orders (
    id          uuid PRIMARY KEY,
    customer_id text NOT NULL,
    origin_port text NOT NULL,
    destination_port text NOT NULL,
    status      text NOT NULL DEFAULT 'placed',
    placed_at   timestamptz NOT NULL DEFAULT now()
);
