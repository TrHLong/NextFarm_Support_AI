from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("TOKEN_SECRET", "unit-test-token-secret-that-is-longer-than-thirty-two-bytes")
try:
    import psycopg  # noqa: F401
except ModuleNotFoundError:
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Database connection was not mocked"))
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    psycopg.rows = rows
    sys.modules.update({"psycopg": psycopg, "psycopg.rows": rows})
