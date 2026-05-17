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

## Part 1 - Running with Docker Compose

```bash
docker-compose up --build -d
py seed.py
```

Seed script adds 6 ingredients and 5 tables. Run it once after first startup.

---

## Part 2 - Kubernetes + Istio

### Requirements

- Docker Desktop
- [KinD](https://kind.sigs.k8s.io/)
- [istioctl](https://istio.io/latest/docs/setup/getting-started/)
- kubectl

> Run all commands in **bash** (Git Bash on Windows) - not PowerShell.

### Setup from scratch

**1. Create cluster:**
```bash
kind create cluster --name restaurant
```

**2. Install Istio:**
```bash
istioctl install --set profile=demo -y
```

**3. Load service images:**
```bash
kind load docker-image microservices-project-order-service:latest --name restaurant
kind load docker-image microservices-project-inventory-service:latest --name restaurant
kind load docker-image microservices-project-billing-service:latest --name restaurant
kind load docker-image microservices-project-reservation-service:latest --name restaurant
```

**4. Install observability addons:**
```bash
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.26/samples/addons/prometheus.yaml
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.26/samples/addons/jaeger.yaml
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.26/samples/addons/kiali.yaml
```

**5. Deploy everything:**
```bash
kubectl apply -k k8s/overlays/local
```

### Accessing services

Port-forward ingress gateway:
```bash
kubectl port-forward svc/istio-ingressgateway -n istio-system 8080:80
```

Then services are available at `http://localhost:8080`:
- `GET /health` - order-service health
- `GET /orders` - list orders
- `GET /items` - inventory items
- `GET /bills` - bills
- `GET /tables` - tables

### Accessing observability tools

```bash
# Kiali - service topology
kubectl port-forward svc/kiali -n istio-system 20001:20001
# open http://localhost:20001

# Prometheus - metrics
kubectl port-forward svc/prometheus -n istio-system 9090:9090
# open http://localhost:9090

# Jaeger - distributed tracing
kubectl port-forward svc/tracing -n istio-system 16686:80
# open http://localhost:16686
```

### Generate test traffic
```bash
for i in {1..50}; do curl -s http://localhost:8080/health; curl -s http://localhost:8080/orders; done
```

### Test fault injection
```bash
# Apply fault injection to inventory-service (50% delay 3s, 20% abort 503)
kubectl apply -f k8s/base/istio/fault-injection.yaml

# Test - some POST /orders requests will take ~3s
curl -s -w "%{http_code} %{time_total}s\n" -o /dev/null -X POST http://localhost:8080/orders \
  -H "Content-Type: application/json" \
  -d '{"table_id":"1","customer_name":"Test","items":[{"name":"pasta","quantity":1,"price":10}]}'

# Remove after testing
kubectl delete -f k8s/base/istio/fault-injection.yaml
```

### Restart existing cluster (after Docker Desktop restart)
```bash
docker start restaurant-control-plane
```

### Delete cluster
```bash
kind delete cluster --name restaurant
```

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
