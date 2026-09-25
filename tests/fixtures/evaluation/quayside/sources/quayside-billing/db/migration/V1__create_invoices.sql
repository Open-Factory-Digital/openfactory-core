CREATE TABLE invoices (
    id            uuid PRIMARY KEY,
    order_id      uuid NOT NULL,
    customer_id   text NOT NULL,
    total         numeric(12, 2) NOT NULL,
    issued_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE invoice_lines (
    id          uuid PRIMARY KEY,
    invoice_id  uuid NOT NULL REFERENCES invoices(id),
    description text NOT NULL,
    amount      numeric(12, 2) NOT NULL
);
