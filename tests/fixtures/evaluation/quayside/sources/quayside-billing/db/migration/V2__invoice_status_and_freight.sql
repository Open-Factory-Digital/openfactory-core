-- REQ-0001: the invoice carries the freight quoted for the order.
ALTER TABLE invoices ADD COLUMN freight_amount numeric(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN status text NOT NULL DEFAULT 'issued';
