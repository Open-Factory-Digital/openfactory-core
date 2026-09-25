CREATE TABLE order_lines (
    id        uuid PRIMARY KEY,
    order_id  uuid NOT NULL REFERENCES orders(id),
    sku       text NOT NULL,
    quantity  integer NOT NULL CHECK (quantity > 0),
    weight_kg numeric(10, 2) NOT NULL
);
