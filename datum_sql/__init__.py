"""Query a Prometheus-compatible metrics store with SQL.

    from datum_sql import connect

    db = connect("http://localhost:8428")
    db.tables()
    db.sql("SELECT * FROM system_cpu_percent WHERE ts > now() - INTERVAL 1 HOUR")

One SELECT becomes one PromQL range query. Joins, GROUP BY and aggregates are
refused rather than silently mistranslated.
"""

from .connection import Connection, Result, connect
from .planner import plan
from .spec import Matcher, QuerySpec, UnsupportedSQL

__all__ = ["Connection", "Matcher", "QuerySpec", "Result", "UnsupportedSQL", "connect", "plan"]
__version__ = "0.1.0"
