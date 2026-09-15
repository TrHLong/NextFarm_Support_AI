"""Allow pure recommender tests to run without a local PostgreSQL driver."""
from __future__ import annotations

import sys
import types

try:
    import psycopg  # noqa: F401
except ModuleNotFoundError:
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Database connection was not mocked"))
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    json_module = types.ModuleType("psycopg.types.json")
    json_module.Jsonb = lambda value: value
    types_module = types.ModuleType("psycopg.types")
    types_module.json = json_module
    psycopg.rows = rows
    psycopg.types = types_module
    sys.modules.update({
        "psycopg": psycopg,
        "psycopg.rows": rows,
        "psycopg.types": types_module,
        "psycopg.types.json": json_module,
    })
