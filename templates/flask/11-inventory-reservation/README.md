# 11 Inventory Reservation with Expiry

Standalone Flask recipe for inventory reservation with optimistic concurrency and TTL-based expiry.

Run: `python run.py`
Test: `python3 -m pytest tests/ -v`

## Endpoints

- `POST /items` create inventory item
- `GET /items/<sku>` get inventory with available quantity
- `POST /reservations` reserve quantity until `expires_at`
- `GET /reservations/<reservation_key>` get reservation state
- `POST /reservations/<reservation_key>/confirm` convert reserved -> committed
- `POST /reservations/<reservation_key>/cancel` release reserved quantity
- `POST /sweeps/expire` expire stale reservations with per-row savepoints

## Notes

- Reservation uses conditional `UPDATE ... WHERE version = ?` and stock check.
- Quantity updates use SQL expressions (`reserved_qty +/- quantity`, `committed_qty + quantity`).
- Expiry sweep isolates row failures with `db.session.begin_nested()`.

## Test

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

Tests use a temporary SQLite database by default. Set `CUBRID_TEST_URL` to run
them against a live CUBRID instance:

```bash
CUBRID_TEST_URL="cubrid+pycubrid://dba@localhost:33000/testdb" python -m pytest tests/ -v
```
