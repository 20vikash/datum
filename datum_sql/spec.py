"""What a translated query looks like, independent of SQL or PromQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Label comparison operators, in PromQL's spelling.
EQUAL = "="
NOT_EQUAL = "!="
MATCHES = "=~"
NOT_MATCHES = "!~"

TIME_COLUMN = "ts"
VALUE_COLUMN = "value"


@dataclass(frozen=True)
class Matcher:
    label: str
    operator: str
    value: str

    def render(self) -> str:
        escaped = self.value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{self.label}{self.operator}"{escaped}"'


@dataclass
class QuerySpec:
    """One metric, one time window, zero or more label filters."""

    metric: str
    start: datetime
    end: datetime
    step: str
    matchers: list[Matcher] = field(default_factory=list)
    # "raw" returns only stored samples; "step" resamples onto a fixed grid,
    # carrying values forward the way a chart wants.
    mode: str = "raw"
    columns: list[str] | None = None
    limit: int | None = None
    order_by: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def selector(self) -> str:
        if not self.matchers:
            return self.metric
        inner = ", ".join(matcher.render() for matcher in sorted(
            self.matchers, key=lambda m: (m.label, m.operator, m.value)
        ))
        return f"{self.metric}{{{inner}}}"

    def describe(self) -> dict:
        return {
            "promql": self.selector,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "step": self.step,
            "mode": self.mode,
            "columns": self.columns,
            "limit": self.limit,
        }


class UnsupportedSQL(Exception):
    """Raised when the SQL asks for something a single PromQL query cannot do."""
