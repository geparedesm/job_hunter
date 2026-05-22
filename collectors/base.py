"""Base collector abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from config.loader import AppConfig


@dataclass(slots=True)
class CollectedJob:
    """Normalized collector output."""

    source: str
    title: str
    company: str
    description: str
    url: str
    external_id: str | None = None
    location: str | None = None
    salary: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    """Abstract API-first collector."""

    source_name: str

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @abstractmethod
    def search(self) -> list[CollectedJob]:
        """Return normalized jobs from the upstream source."""
