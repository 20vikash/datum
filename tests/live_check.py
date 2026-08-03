"""End-to-end check against a real VictoriaMetrics. Not part of the unit suite."""

import sys

from datum_sql import UnsupportedSQL, connect

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8428"
db = connect(URL)

print("=== CATALOG ===")
print("  tables :", db.tables())
print("  columns:", db.columns("system_cpu_percent"))
print("  regions:", db.distinct("system_cpu_percent", "region"))

QUERIES = [
    """SELECT * FROM system_cpu_percent
       WHERE ts > now() - INTERVAL 10 MINUTE""",
    """SELECT source_id, value FROM system_cpu_percent
       WHERE region = 'ap-south-1' AND ts > now() - INTERVAL 10 MINUTE""",
    """SELECT source_id, value FROM system_cpu_percent
       WHERE source_id LIKE 'srv-%' AND ts > now() - INTERVAL 10 MINUTE""",
    """SELECT source_id, region, value FROM system_cpu_percent
       WHERE region IN ('us-east-1', 'eu-west-1') AND ts > now() - INTERVAL 10 MINUTE""",
    """SELECT source_id, value FROM system_cpu_percent
       WHERE ts > now() - INTERVAL 10 MINUTE ORDER BY value DESC LIMIT 3""",
    """SELECT * FROM system_cpu_percent
       WHERE labels['region'] = 'ap-south-1' AND ts > now() - INTERVAL 10 MINUTE""",
]

for query in QUERIES:
    print()
    print("SQL   :", " ".join(query.split())[:100])
    plan = db.explain(query)
    print("PromQL:", plan["promql"], "| step", plan["step"])
    result = db.sql(query)
    print("rows  :", len(result), "| columns", result.columns)
    for row in result.tuples()[:3]:
        print("        ", row)

print()
print("=== REFUSED, with the reason ===")
for bad in [
    "SELECT * FROM a JOIN b ON a.x = b.x",
    "SELECT avg(value) FROM system_cpu_percent",
    "SELECT region, count(*) FROM system_cpu_percent GROUP BY region",
    "SELECT * FROM system_cpu_percent WHERE value > 80",
    "SELECT * FROM system_cpu_percent WHERE region = 'a' OR region = 'b'",
]:
    try:
        db.sql(bad)
        print(f"  {bad[:48]:50} -> NOT REFUSED (bug)")
    except UnsupportedSQL as error:
        print(f"  {bad[:48]:50} -> {str(error)[:58]}")
