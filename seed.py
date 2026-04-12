"""
Seed script - fills the system with starting data for demo purposes.

Run this once after docker-compose up -d:
  python seed.py
  OR
  py seed.py
"""

import httpx

INVENTORY_URL = "http://localhost:8002"
RESERVATION_URL = "http://localhost:8004"


def check_health():
    """Check that all services are running before we start."""
    print("Checking that all services are running...")
    services = {
        "order-service":       "http://localhost:8001/health",
        "inventory-service":   "http://localhost:8002/health",
        "billing-service":     "http://localhost:8003/health",
        "reservation-service": "http://localhost:8004/health",
    }
    all_ok = True
    for name, url in services.items():
        try:
            r = httpx.get(url, timeout=3)
            print(f"  OK - {name}")
        except Exception:
            print(f"  FAILED - {name} is not responding. Run docker-compose up --build first.")
            all_ok = False
    return all_ok


def seed_ingredients():
    """Add starting ingredients to the inventory service."""
    print("\nAdding ingredients...")
    ingredients = [
        {"name": "pasta",        "quantity": 100, "unit": "kg",     "threshold": 10},
        {"name": "tomato sauce", "quantity": 80,  "unit": "litres", "threshold": 8},
        {"name": "chicken",      "quantity": 50,  "unit": "kg",     "threshold": 5},
        {"name": "salad",        "quantity": 40,  "unit": "kg",     "threshold": 5},
        {"name": "cheese",       "quantity": 30,  "unit": "kg",     "threshold": 3},
        {"name": "pizza dough",  "quantity": 60,  "unit": "kg",     "threshold": 6},
    ]
    for ing in ingredients:
        r = httpx.post(f"{INVENTORY_URL}/inventory", json=ing)
        if r.status_code == 200:
            print(f"  OK - {ing['name']} ({ing['quantity']} {ing['unit']})")
        else:
            print(f"  FAILED - {ing['name']}: {r.text}")


def seed_tables():
    """Add restaurant tables to the reservation service."""
    print("\nAdding tables...")
    tables = [
        {"number": "T1", "capacity": 2},
        {"number": "T2", "capacity": 4},
        {"number": "T3", "capacity": 4},
        {"number": "T4", "capacity": 6},
        {"number": "T5", "capacity": 8},
    ]
    for table in tables:
        r = httpx.post(f"{RESERVATION_URL}/tables", json=table)
        if r.status_code == 200:
            data = r.json()
            print(f"  OK - Table {table['number']} (capacity {table['capacity']}) id: {data['id']}")
        else:
            print(f"  FAILED - Table {table['number']}: {r.text}")


if __name__ == "__main__":
    print("=" * 50)
    print("  Restaurant Platform - Seed Script")
    print("=" * 50)

    if not check_health():
        print("\nStopped: not all services are available.")
        exit(1)

    seed_ingredients()
    seed_tables()

    print("\n" + "=" * 50)
    print("  Done! Swagger UI is available at:")
    print("  http://localhost:8001/docs  (order-service)")
    print("  http://localhost:8002/docs  (inventory-service)")
    print("  http://localhost:8003/docs  (billing-service)")
    print("  http://localhost:8004/docs  (reservation-service)")
    print("=" * 50)
