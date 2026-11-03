
"""Day 15: Base normalizer class and shared normalization helpers."""

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


# DocuSign can return up to 7 fractional digits.
# Python datetime supports a maximum of 6.
_FRAC = re.compile(r"(\.\d{6})\d+")


def parse_dt(value: Any) -> datetime | None:
    """
    Convert an ISO 8601 date string into a datetime object.

    Handles:
    - UTC timestamps ending in Z
    - Timezone offsets
    - Up to 7 fractional second digits
    - Missing or invalid values

    Returns None for invalid or unsupported values.
    """
    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()

    # Truncate fractional seconds to Python's 6-digit precision.
    value = _FRAC.sub(r"\1", value)

    # Convert trailing Z to the UTC offset expected by fromisoformat.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(value)
    except (ValueError, OverflowError):
        return None


def safe_get(
    data: Any,
    *keys: str,
    default: Any = None,
) -> Any:
    """
    Safely retrieve a nested value from dictionaries.

    Example:
        safe_get(data, "customFields", "textCustomFields")
    """
    current = data

    for key in keys:
        if not isinstance(current, dict):
            return default

        current = current.get(key)

        if current is None:
            return default

    return current


class Normalizer(ABC):
    """
    Base interface for all DocuSign normalizers.

    Each normalizer converts a list of raw records into
    a dictionary containing normalized table records.

    Expected output:
        {
            "table_name": [
                {"field": "value"}
            ]
        }
    """

    table_name: str = ""

    @abstractmethod
    def normalize(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Normalize multiple raw records.

        Subclasses must implement this method.
        """
        raise NotImplementedError

    def normalize_many(
        self,
        record_groups: list[list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Normalize multiple batches and combine their results.
        """
        combined: dict[str, list[dict[str, Any]]] = {}

        for records in record_groups:
            result = self.normalize(records)

            for table, rows in result.items():
                combined.setdefault(table, []).extend(rows)

        return combined
