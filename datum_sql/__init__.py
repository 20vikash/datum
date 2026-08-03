"""Translate a narrow dialect of SQL into PromQL.

    from datum_sql import plan, shape

    spec = plan("SELECT * FROM system_cpu_percent WHERE ts > now() - INTERVAL 1 HOUR")
    spec.selector
    result = shape(rows_you_fetched, spec)

One SELECT becomes one PromQL range query. Joins, GROUP BY and aggregates are
refused rather than silently mistranslated. Fetching is the caller's job; this
package opens no sockets.
"""

from .planner import plan
from .rows import Result, infer_columns, shape
from .spec import Matcher, QuerySpec, UnsupportedSQL

__all__ = [
    "Matcher",
    "QuerySpec",
    "Result",
    "UnsupportedSQL",
    "infer_columns",
    "plan",
    "shape",
]
__version__ = "0.1.0"
