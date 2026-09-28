# 10 Workflow Engine (DAG)

Standalone Flask recipe that models workflow definitions and workflow runs with DAG-based execution.

Run: `python run.py`
Test: `python3 -m pytest tests/ -v`

## Endpoints

- `POST /workflows`
- `GET /workflows/<workflow_key>`
- `POST /workflow-runs`
- `GET /workflow-runs/<run_key>`
- `POST /workflow-runs/<run_key>/tick`
- `POST /workflow-step-runs/<id>/approve`
- `POST /workflow-step-runs/<id>/retry`
- `POST /workflow-step-runs/<id>/skip`

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
