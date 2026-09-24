"""Optional third-party metric providers.

Volume, difficulty, domain authority, backlinks, and Core Web Vitals
are not computed in-app. Callers must treat None as "Data unavailable"
and never invent numbers.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol


UNAVAILABLE = "Data unavailable"


class MetricProvider(Protocol):
    def keyword_volume(self, phrase: str, country: str) -> Optional[int]: ...
    def keyword_difficulty(self, phrase: str, country: str) -> Optional[int]: ...
    def domain_authority(self, host: str) -> Optional[int]: ...
    def referring_domains(self, url: str) -> Optional[int]: ...
    def core_web_vitals(self, url: str) -> Optional[dict[str, Any]]: ...


class NullMetricProvider:
    """Default provider: no paid SEO APIs are configured."""

    def keyword_volume(self, phrase: str, country: str) -> Optional[int]:
        return None

    def keyword_difficulty(self, phrase: str, country: str) -> Optional[int]:
        return None

    def domain_authority(self, host: str) -> Optional[int]:
        return None

    def referring_domains(self, url: str) -> Optional[int]:
        return None

    def core_web_vitals(self, url: str) -> Optional[dict[str, Any]]:
        return None


DEFAULT_METRICS: MetricProvider = NullMetricProvider()


def label(value: Any) -> Any:
    return UNAVAILABLE if value is None or value == "" else value
