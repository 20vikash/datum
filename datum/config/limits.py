from __future__ import annotations

# Bytes on the wire, refused before anything reads them. Every route, because
# `/v1/query` carries no other cap at all.
MAX_BODY = 8 * 1024 * 1024

# Bytes after snappy, remote write only. Measured at roughly 20:1 on protobuf,
# so MAX_BODY alone does not bound what a body costs once it is open.
MAX_DECOMPRESSED = 12 * 1024 * 1024

# Readings in one write, both paths. Remote write counts them off the wire
# before parsing; the JSON path reaches it after, where pydantic already has the
# list in memory.
MAX_BATCH = 10_000

# Labels on one series. Nothing in the wire format bounds them, and a series
# carrying a million costs a fraction of a megabyte to send. Real producers use
# a handful: node_exporter's widest is well under twenty.
MAX_LABELS = 64

# Rows in one read, and seconds to connect or execute. Applied by ClickHouse
# rather than here, and both are overridable per deployment.
MAX_ROWS = 100_000
TIMEOUT = 30.0
