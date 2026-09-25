# Quayside Freight

Quotes the freight of a shipment between two ports, over gRPC. It keeps no database: the rates
are a table in the code.

- `proto/freight/v1/freight.proto` — the gRPC service
- `freight/quote.py` — the freight calculation
