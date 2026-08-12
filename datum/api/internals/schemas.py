from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from datum.config.limits import MAX_BATCH, MAX_LABELS, MAX_RESOURCE_ID

NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class Sample(BaseModel):
    """One reading. `resource_id` is absent by design: the token decides it."""

    metric: str = Field(pattern=NAME.pattern, max_length=200)
    value: float
    ts: datetime
    labels: dict[str, str] = Field(default_factory=dict, max_length=MAX_LABELS)

    @field_validator("labels")
    @classmethod
    def _label_names(cls, labels: dict[str, str]) -> dict[str, str]:
        unusable = sorted(name for name in labels if not NAME.match(name))
        if unusable:
            raise ValueError(f"label names must match {NAME.pattern}: {', '.join(unusable)}")
        return labels

    def get_row(self, resource_id: str) -> dict:
        """One table row. The token owns `resource_id`, so a claimed one is dropped."""
        labels = {name: value for name, value in self.labels.items() if name != "resource_id"}
        return {
            "ts": self.ts,
            "metric": self.metric,
            "resource_id": resource_id,
            "labels": labels,
            "value": self.value,
        }


class SamplesRequest(BaseModel):
    samples: list[Sample] = Field(min_length=1, max_length=MAX_BATCH)


class IngestResponse(BaseModel):
    accepted: int


ResourceStatus = Literal["Active", "Terminated", "Pending"]
TERMINATED: ResourceStatus = "Terminated"


class Resource(BaseModel):
    """Unlike a sample, the id comes from the body: an admin speaks for the fleet."""

    resource_id: str = Field(min_length=1, max_length=MAX_RESOURCE_ID)
    status: ResourceStatus


class ResourceUpdate(BaseModel):
    status: ResourceStatus


class ResourceResponse(BaseModel):
    accepted: int
