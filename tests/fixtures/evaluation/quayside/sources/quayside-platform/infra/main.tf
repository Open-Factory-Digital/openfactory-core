# What Quayside runs on in production, beside the cluster.

variable "orders_db_password" {
  type      = string
  sensitive = true
}

resource "aws_db_instance" "orders" {
  identifier     = "quayside-orders"
  engine         = "postgres"
  instance_class = "db.t4g.small"
  password       = var.orders_db_password
}

# Invoices are emailed from a queue billing fills.
resource "aws_sqs_queue" "invoice_emails" {
  name                      = "quayside-invoice-emails"
  message_retention_seconds = 345600
}

module "network" {
  source = "git::https://example.invalid/quayside/terraform-network.git?ref=v2"
}
