"""SQL -> QuerySpec.

Deliberately narrow. One metric, a time window, label filters, projection,
ORDER BY and LIMIT. Anything a single PromQL query cannot express is refused
with a message that names the offending construct, rather than quietly
returning the wrong rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlglot
from sqlglot import expressions as exp

from datum_sql.spec import (
    EQUAL,
    MATCHES,
    NOT_EQUAL,
    NOT_MATCHES,
    TIME_COLUMN,
    VALUE_COLUMN,
    Matcher,
    QuerySpec,
    UnsupportedSQL,
)

DEFAULT_WINDOW = timedelta(hours=1)
TARGET_POINTS = 500
MIN_STEP_SECONDS = 5

REFUSED = {
    exp.Join: "JOIN",
    exp.Group: "GROUP BY",
    exp.Having: "HAVING",
    exp.Union: "UNION",
    exp.Window: "window function",
    exp.Subquery: "subquery",
}

INTERVAL_UNITS = {
    "second": "seconds",
    "seconds": "seconds",
    "sec": "seconds",
    "minute": "minutes",
    "minutes": "minutes",
    "min": "minutes",
    "hour": "hours",
    "hours": "hours",
    "day": "days",
    "days": "days",
    "week": "weeks",
    "weeks": "weeks",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


# Only the characters RE2 actually treats as special. re.escape() also escapes
# things like '-', which then collide with PromQL's own string escaping and
# produce queries that are correct but unreadable.
REGEX_METACHARACTERS = set(r".\+*?()[]{}^$|")


def escape_regex(text: str) -> str:
    return "".join("\\" + c if c in REGEX_METACHARACTERS else c for c in text)


def like_to_regex(pattern: str) -> str:
    """SQL LIKE -> RE2. PromQL anchors regexes, so no ^ or $ needed."""
    out = []
    for character in pattern:
        if character == "%":
            out.append(".*")
        elif character == "_":
            out.append(".")
        else:
            out.append(escape_regex(character))
    return "".join(out)


def _refuse(statement: exp.Expression) -> None:
    for node_type, name in REFUSED.items():
        if list(statement.find_all(node_type)):
            raise UnsupportedSQL(
                f"{name} is not supported. This connector maps one metric to one "
                f"PromQL query; combine results in your application instead."
            )
    for projection in statement.expressions:
        if list(projection.find_all(exp.AggFunc)):
            raise UnsupportedSQL(
                "Aggregate functions are not supported. Select raw samples and "
                "aggregate in your application."
            )


def _evaluate_time(node: exp.Expression) -> datetime:
    """Resolve a time expression to an absolute instant."""
    if isinstance(node, exp.Cast):
        return _evaluate_time(node.this)
    if isinstance(node, exp.Paren):
        return _evaluate_time(node.this)
    if isinstance(node, (exp.CurrentTimestamp, exp.CurrentDate)):
        return _now()
    if isinstance(node, exp.Anonymous) and node.name.lower() in {"now", "current_timestamp"}:
        return _now()
    if isinstance(node, (exp.Sub, exp.Add)):
        base = _evaluate_time(node.this)
        delta = _evaluate_interval(node.expression)
        return base - delta if isinstance(node, exp.Sub) else base + delta
    if isinstance(node, exp.Literal):
        return _parse_timestamp(node.this)
    raise UnsupportedSQL(f"Cannot interpret time expression: {node.sql()}")


def _evaluate_interval(node: exp.Expression) -> timedelta:
    if isinstance(node, exp.Paren):
        return _evaluate_interval(node.this)
    if not isinstance(node, exp.Interval):
        raise UnsupportedSQL(f"Expected an INTERVAL, got: {node.sql()}")
    raw = node.this
    amount = float(raw.this if isinstance(raw, exp.Literal) else raw)
    unit = (node.unit.name if node.unit else "second").lower()
    if unit not in INTERVAL_UNITS:
        raise UnsupportedSQL(f"Unsupported interval unit: {unit}")
    return timedelta(**{INTERVAL_UNITS[unit]: amount})


def _parse_timestamp(raw: str) -> datetime:
    text = str(raw).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), UTC)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _flatten_and(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _flatten_and(node.this) + _flatten_and(node.expression)
    if isinstance(node, exp.Paren):
        return _flatten_and(node.this)
    return [node]


def _column_name(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Column):
        return node.name
    # labels['region'] style access, for compatibility with the Presto shape
    if isinstance(node, exp.Bracket) and isinstance(node.this, exp.Column):
        keys = node.expressions
        if len(keys) == 1 and isinstance(keys[0], exp.Literal):
            return str(keys[0].this)
    return None


def _literal(node: exp.Expression) -> str:
    if isinstance(node, exp.Literal):
        return str(node.this)
    raise UnsupportedSQL(f"Expected a literal value, got: {node.sql()}")


def _choose_step(start: datetime, end: datetime, requested: str | None) -> str:
    if requested:
        return requested
    span = max(1, int((end - start).total_seconds()))
    step = max(MIN_STEP_SECONDS, span // TARGET_POINTS)
    return f"{step}s"


def _projection(statement: exp.Select) -> list[str] | None:
    """None means SELECT *."""
    if any(isinstance(item, exp.Star) for item in statement.expressions):
        return None
    columns = []
    for item in statement.expressions:
        target = item.this if isinstance(item, exp.Alias) else item
        name = _column_name(target)
        if name is None:
            raise UnsupportedSQL(f"Cannot project expression: {item.sql()}")
        columns.append(item.alias_or_name if isinstance(item, exp.Alias) else name)
    return columns


def _limit_of(statement: exp.Select) -> int | None:
    node = statement.args.get("limit")
    return int(node.expression.this) if node is not None else None


def _offset_of(statement: exp.Select) -> int:
    node = statement.args.get("offset")
    return int(node.expression.this) if node is not None else 0


def _order_of(statement: exp.Select) -> list[tuple[str, bool]]:
    node = statement.args.get("order")
    if node is None:
        return []
    order = []
    for ordered in node.expressions:
        name = _column_name(ordered.this)
        if name is None:
            raise UnsupportedSQL(f"Cannot order by: {ordered.sql()}")
        order.append((name, bool(ordered.args.get("desc"))))
    return order


def plan(
    sql: str,
    dialect: str = "mysql",
    step: str | None = None,
    default_window: timedelta = DEFAULT_WINDOW,
    mode: str = "raw",
) -> QuerySpec:
    statement = sqlglot.parse_one(sql, read=dialect)
    # Refused constructs are named first: a UNION is not a Select, and saying so
    # sends the caller looking for a missing SELECT that is right there.
    _refuse(statement)
    if not isinstance(statement, exp.Select):
        raise UnsupportedSQL("Only SELECT statements are supported.")

    # sqlglot renamed the FROM arg key between major versions; find the node
    # instead of reaching into args. Joins and subqueries are already refused,
    # so exactly one table must remain.
    tables = list(statement.find_all(exp.Table))
    if len(tables) != 1:
        raise UnsupportedSQL("Expected exactly one metric in FROM.")
    metric = tables[0].name

    start: datetime | None = None
    end: datetime | None = None
    matchers: list[Matcher] = []

    where = statement.args.get("where")
    if where is not None:
        for predicate in _flatten_and(where.this):
            outcome = _translate_predicate(predicate)
            if outcome[0] == "start":
                start = outcome[1] if start is None else max(start, outcome[1])
            elif outcome[0] == "end":
                end = outcome[1] if end is None else min(end, outcome[1])
            else:
                matchers.append(outcome[1])

    end = end or _now()
    start = start or (end - default_window)
    if start >= end:
        raise UnsupportedSQL("Time window is empty: start is not before end.")

    columns = _projection(statement)
    limit = _limit_of(statement)
    offset = _offset_of(statement)
    order_by = _order_of(statement)

    return QuerySpec(
        metric=metric,
        start=start,
        end=end,
        step=_choose_step(start, end, step),
        matchers=matchers,
        columns=columns,
        limit=limit,
        offset=offset,
        order_by=order_by,
        mode=mode,
    )


def _translate_predicate(node: exp.Expression) -> tuple[str, object]:
    if isinstance(node, exp.Paren):
        return _translate_predicate(node.this)

    if isinstance(node, exp.In):
        name = _column_name(node.this)
        if name is None:
            raise UnsupportedSQL(f"Unsupported IN target: {node.sql()}")
        options = [escape_regex(_literal(item)) for item in node.expressions]
        if not options:
            raise UnsupportedSQL("IN () with no values.")
        return "matcher", Matcher(name, MATCHES, "|".join(options))

    if isinstance(node, (exp.Like, exp.ILike)):
        name = _column_name(node.this)
        if name is None:
            raise UnsupportedSQL(f"Unsupported LIKE target: {node.sql()}")
        pattern = like_to_regex(_literal(node.expression))
        if isinstance(node, exp.ILike):
            pattern = f"(?i){pattern}"
        return "matcher", Matcher(name, MATCHES, pattern)

    if isinstance(node, exp.RegexpLike):
        name = _column_name(node.this)
        if name is None:
            raise UnsupportedSQL(f"Unsupported REGEXP target: {node.sql()}")
        return "matcher", Matcher(name, MATCHES, _literal(node.expression))

    if isinstance(node, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
        name = _column_name(node.this)
        if name is None:
            raise UnsupportedSQL(f"Unsupported predicate: {node.sql()}")

        if name == TIME_COLUMN:
            moment = _evaluate_time(node.expression)
            if isinstance(node, (exp.GT, exp.GTE)):
                return "start", moment
            if isinstance(node, (exp.LT, exp.LTE)):
                return "end", moment
            raise UnsupportedSQL("Equality on the time column is not supported; use a range.")

        if name == VALUE_COLUMN:
            raise UnsupportedSQL(
                "Filtering on value is not supported. A selector matches labels only, "
                "so filter on value in your application."
            )

        if isinstance(node, exp.EQ):
            return "matcher", Matcher(name, EQUAL, _literal(node.expression))
        if isinstance(node, exp.NEQ):
            return "matcher", Matcher(name, NOT_EQUAL, _literal(node.expression))
        raise UnsupportedSQL(f"Cannot compare label {name} with {type(node).__name__}.")

    if isinstance(node, exp.Between) and _column_name(node.this) == TIME_COLUMN:
        raise UnsupportedSQL("Use ts >= ... AND ts <= ... instead of BETWEEN.")

    if isinstance(node, exp.Not) and isinstance(node.this, (exp.Like, exp.ILike)):
        matcher = _translate_predicate(node.this)[1]
        return "matcher", Matcher(matcher.label, NOT_MATCHES, matcher.value)

    if isinstance(node, exp.Or):
        raise UnsupportedSQL("OR is not supported. Use IN (...) for alternatives on one label.")

    raise UnsupportedSQL(f"Unsupported WHERE clause: {node.sql()}")
