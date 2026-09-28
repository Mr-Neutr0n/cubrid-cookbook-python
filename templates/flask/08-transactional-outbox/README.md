# 08 Transactional Outbox

Invoice events with outbox lease/ack/fail/dead-letter flow recipe.

Run: `python run.py`

## Test

```bash
pip install -r requirements.txt pytest httpx
python3 -m pytest tests/ -v
```

Tests use a temporary SQLite database by default. Set `CUBRID_TEST_URL` to run
them against a live CUBRID instance:

```bash
CUBRID_TEST_URL="cubrid+pycubrid://dba@localhost:33000/testdb" python3 -m pytest tests/ -v
```
