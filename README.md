# Restaurant Operations Platform

Multi-service system for managing restaurant operations including table reservations, order processing, inventory tracking and billing.

## Tech Stack

- **FastAPI** - REST API with validation and async support
- **PostgreSQL** - separate database per service
- **Redis Streams** - async messaging between services
- **Docker Compose** - runs everything together

## Services

| Service | Port | Responsibility |
|---|---|---|
| order-service | 8001 | Order lifecycle, Saga orchestrator, CQRS, Outbox |
| inventory-service | 8002 | Ingredient stock, reservations and releases |
| billing-service | 8003 | Bills and payments |
| reservation-service | 8004 | Table bookings |

## Running the System

```bash
docker-compose up --build -d
py seed.py
```

Seed script adds 6 ingredients and 5 tables. Run it once after first startup.

## API Docs

Each service has Swagger UI at `/docs`:

- http://localhost:8001/docs
- http://localhost:8002/docs
- http://localhost:8003/docs
- http://localhost:8004/docs

## Testing the Patterns

### Saga - succesful path

Place an order with an ingredient that exists in inventory (e.g. pasta):

```
POST http://localhost:8001/orders
{
  "table_id": "...",
  "customer_name": "John",
  "items": [{"name": "pasta", "quantity": 1, "price": 12.50}]
}
```

Order goes PENDING > inventory reserved > bill created > CONFIRMED.

### Saga - failure and compensation

Place an order with an ingredient that does not exist:

```
POST http://localhost:8001/orders
{
  "table_id": "...",
  "customer_name": "Jane",
  "items": [{"name": "truffle", "quantity": 1, "price": 50.00}]
}
```

Inventory service returns error, order gets CANCELLED, nothing is reserved.

### CQRS - kitchen read model

```
GET http://localhost:8001/orders/kitchen/active
```

This reads from order_projections table, not the main orders table.

### Outbox worker

Watch docker-compose logs after placing an order. You will see:

```
[OUTBOX] Published event: ORDER_CREATED
[OUTBOX] Published event: ORDER_CONFIRMED
```

### Payment failure

First move the order through all statuses using `PATCH http://localhost:8001/orders/{id}`:

```
{"status": "IN_PREPARATION"}
{"status": "READY"}
{"status": "SERVED"}
```

Then try to pay:

```
POST http://localhost:8003/bills/{order_id}/pay
```

Payment has 20% random failure rate. On failure you get 400 and bill status is FAILED.
Call the same endpoint again to retry. Order Service and Inventory Service are not affected at all.
