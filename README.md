# Eagle
A Finance Controller

## Project Setup

### Dependencies

This project uses standard `requirements.txt` for dependency management.

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### Configuration

The project separates configuration into two types:

1. **Runtime / Environment Configuration**: Infrastructure settings (database paths, API keys, model choices) are managed via environment variables. See `.env.example`. Do NOT hardcode API credentials.
2. **Reconciliation Rules**: Project-defined constants (tolerances, settlement timing thresholds) are strictly version-controlled within `src/eagle/reconciliation/constants.py` and are not read from the environment to ensure reproducible evaluation.

### Testing

Run the test suite with:

```bash
pytest
```
