from datetime import UTC, datetime, timedelta

import pytest

from datum_sql import UnsupportedSQL, plan


def promql(sql: str) -> str:
    return plan(sql).selector


def test_bare_select_becomes_the_metric_name():
    assert promql("SELECT * FROM system_cpu_percent") == "system_cpu_percent"


def test_equality_becomes_a_label_matcher():
    assert promql(
        "SELECT * FROM system_cpu_percent WHERE region = 'ap-south-1'"
    ) == 'system_cpu_percent{region="ap-south-1"}'


def test_inequality_becomes_a_negated_matcher():
    assert promql(
        "SELECT * FROM cpu WHERE region != 'eu'"
    ) == 'cpu{region!="eu"}'


def test_multiple_labels_are_sorted_for_a_stable_query():
    assert promql(
        "SELECT * FROM cpu WHERE region = 'ap' AND bench = 'main'"
    ) == 'cpu{bench="main", region="ap"}'


def test_like_becomes_a_regex_matcher():
    assert promql(
        "SELECT * FROM cpu WHERE source_id LIKE 'srv-%'"
    ) == 'cpu{source_id=~"srv-.*"}'


def test_regex_metacharacters_in_like_are_escaped():
    assert plan(
        "SELECT * FROM cpu WHERE source_id LIKE 'a.b%'"
    ).selector == 'cpu{source_id=~"a\\\\.b.*"}'


def test_in_becomes_an_alternation():
    assert promql(
        "SELECT * FROM cpu WHERE region IN ('ap', 'us')"
    ) == 'cpu{region=~"ap|us"}'


def test_labels_map_access_is_accepted_for_presto_compatibility():
    assert promql(
        "SELECT * FROM cpu WHERE labels['region'] = 'ap'"
    ) == 'cpu{region="ap"}'


def test_time_predicates_set_the_window_not_a_matcher():
    spec = plan("SELECT * FROM cpu WHERE ts > now() - INTERVAL 2 HOUR")
    assert spec.selector == "cpu"
    assert timedelta(minutes=115) < (spec.end - spec.start) < timedelta(minutes=125)


def test_absolute_timestamps_are_honoured():
    spec = plan(
        "SELECT * FROM cpu WHERE ts >= '2026-08-01T00:00:00Z' AND ts <= '2026-08-01T06:00:00Z'"
    )
    assert spec.start == datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    assert spec.end == datetime(2026, 8, 1, 6, 0, tzinfo=UTC)


def test_window_defaults_to_one_hour_when_unbounded():
    spec = plan("SELECT * FROM cpu")
    assert timedelta(minutes=55) < (spec.end - spec.start) < timedelta(minutes=65)


def test_step_scales_with_the_window():
    narrow = plan("SELECT * FROM cpu WHERE ts > now() - INTERVAL 1 HOUR")
    wide = plan("SELECT * FROM cpu WHERE ts > now() - INTERVAL 7 DAY")
    assert int(narrow.step.rstrip("s")) < int(wide.step.rstrip("s"))


def test_projection_and_limit_are_captured():
    spec = plan("SELECT source_id, value FROM cpu LIMIT 10")
    assert spec.columns == ["source_id", "value"]
    assert spec.limit == 10


def test_order_by_direction_is_captured():
    spec = plan("SELECT * FROM cpu ORDER BY value DESC")
    assert spec.order_by == [("value", True)]


@pytest.mark.parametrize(
    "sql, missing",
    [
        ("SELECT * FROM a JOIN b ON a.x = b.x", "JOIN"),
        ("SELECT region, count(*) FROM cpu GROUP BY region", "GROUP BY"),
        ("SELECT avg(value) FROM cpu", "Aggregate"),
        ("SELECT * FROM cpu WHERE region = 'a' OR region = 'b'", "OR"),
        ("SELECT * FROM cpu WHERE value > 80", "value"),
        ("SELECT * FROM cpu UNION ALL SELECT * FROM mem", "UNION"),
        ("SELECT * FROM cpu UNION SELECT * FROM mem", "UNION"),
    ],
)
def test_unsupported_sql_is_refused_by_name(sql, missing):
    with pytest.raises(UnsupportedSQL) as caught:
        plan(sql)
    assert missing.lower() in str(caught.value).lower()


def test_quotes_in_label_values_are_escaped():
    spec = plan("""SELECT * FROM cpu WHERE region = 'a"b'""")
    assert '\\"' in spec.selector


def test_pagination_is_honoured_by_default():
    """Standalone callers get what SQL means."""
    spec = plan("SELECT * FROM cpu LIMIT 10 OFFSET 5")

    assert (spec.limit, spec.offset) == (10, 5)


def test_ignore_pagination_drops_the_page_window():
    spec = plan("SELECT * FROM cpu LIMIT 100 OFFSET 200", ignore_pagination=True)

    assert (spec.limit, spec.offset) == (None, 0)


def test_ignore_pagination_unwraps_the_subquery():
    """What a BI tool sends once the query it was given already had a LIMIT."""
    sql = "SELECT * FROM (SELECT * FROM cpu WHERE region = 'ap' LIMIT 10) AS t0 LIMIT 100 OFFSET 100"

    spec = plan(sql, ignore_pagination=True)

    assert spec.selector == 'cpu{region="ap"}'
    assert (spec.limit, spec.offset) == (None, 0)


def test_ignore_pagination_keeps_order_by():
    spec = plan("SELECT * FROM cpu ORDER BY value DESC LIMIT 100", ignore_pagination=True)

    assert spec.order_by == [("value", True)]
    assert spec.limit is None


def test_ignore_pagination_keeps_outer_order_over_a_subquery():
    sql = "SELECT * FROM (SELECT * FROM cpu LIMIT 5) AS t0 ORDER BY ts LIMIT 100"

    spec = plan(sql, ignore_pagination=True)

    assert spec.order_by == [("ts", False)]


def test_ignore_pagination_keeps_projection_and_matchers():
    sql = "SELECT ts, value FROM (SELECT * FROM cpu WHERE host != 'z' LIMIT 5) t0 LIMIT 100"

    spec = plan(sql, ignore_pagination=True)

    assert spec.selector == 'cpu{host!="z"}'


def test_ignore_pagination_still_refuses_real_sql():
    """Stripping the page window must not smuggle anything past the refusals."""
    with pytest.raises(UnsupportedSQL) as caught:
        plan("SELECT region, avg(value) FROM cpu GROUP BY region LIMIT 100", ignore_pagination=True)
    assert "group by" in str(caught.value).lower()
