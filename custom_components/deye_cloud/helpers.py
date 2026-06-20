"""Shared utility functions for the Deye Cloud integration."""

from __future__ import annotations

import re


def generate_entity_id(
    device_name: str,
    sensor_type: str,
    channel_or_phase: int | None = None,
    platform: str = "sensor",
) -> str:
    """Generate an entity ID following the naming convention.

    Pattern for multi-instance: {platform}.{device_name}_{sensor_type}_{channel_or_phase}
    Pattern for single-instance: {platform}.{device_name}_{sensor_type}

    Args:
        device_name: The device name (will be slugified).
        sensor_type: The sensor type identifier (e.g., "pv_power", "battery_soc").
        channel_or_phase: Optional channel or phase number for multi-instance sensors.
        platform: The entity platform (default: "sensor").

    Returns:
        A formatted entity ID string.
    """
    slug = _slugify(device_name)
    if channel_or_phase is not None:
        return f"{platform}.{slug}_{sensor_type}_{channel_or_phase}"
    return f"{platform}.{slug}_{sensor_type}"


def generate_unique_id(
    device_sn: str,
    sensor_type: str,
    channel_or_phase: int | None = None,
) -> str:
    """Generate a stable unique ID for an entity.

    Incorporates the inverter serial number to prevent collisions
    across multiple inverters.

    Args:
        device_sn: The device serial number.
        sensor_type: The sensor type identifier.
        channel_or_phase: Optional channel or phase number.

    Returns:
        A unique ID string.
    """
    if channel_or_phase is not None:
        return f"{device_sn}_{sensor_type}_{channel_or_phase}"
    return f"{device_sn}_{sensor_type}"


def validate_time_format(time_str: str) -> bool:
    """Validate that a time string is in HH:MM format.

    Args:
        time_str: The time string to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not isinstance(time_str, str):
        return False
    match = re.match(r"^(\d{2}):(\d{2})$", time_str)
    if not match:
        return False
    hours = int(match.group(1))
    minutes = int(match.group(2))
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def time_to_minutes(time_str: str) -> int:
    """Convert a HH:MM time string to minutes since midnight.

    Args:
        time_str: A valid HH:MM time string.

    Returns:
        Minutes since midnight (0-1439).

    Raises:
        ValueError: If the time string is not in valid HH:MM format.
    """
    if not validate_time_format(time_str):
        raise ValueError(f"Invalid time format: '{time_str}'. Expected HH:MM.")
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def check_time_periods_overlap(
    periods: list[tuple[str, str]],
) -> bool:
    """Check if any time periods overlap.

    Each period is a tuple of (start_time, end_time) in HH:MM format.
    Periods where end_time <= start_time are considered invalid (they wrap
    around midnight) and are treated as invalid input rather than overlapping.

    Args:
        periods: List of (start_time, end_time) tuples in HH:MM format.

    Returns:
        True if any periods overlap, False if no overlaps exist.

    Raises:
        ValueError: If any time string is not in valid HH:MM format.
    """
    if len(periods) <= 1:
        return False

    # Convert to minutes and validate
    intervals: list[tuple[int, int]] = []
    for start_str, end_str in periods:
        start_min = time_to_minutes(start_str)
        end_min = time_to_minutes(end_str)
        intervals.append((start_min, end_min))

    # Check each pair for overlap
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            if _intervals_overlap(intervals[i], intervals[j]):
                return True

    return False


def validate_time_period(start_time: str, end_time: str) -> bool:
    """Validate that a time period has end_time strictly after start_time.

    Args:
        start_time: Start time in HH:MM format.
        end_time: End time in HH:MM format.

    Returns:
        True if the period is valid (end > start), False otherwise.

    Raises:
        ValueError: If either time string is not in valid HH:MM format.
    """
    start_min = time_to_minutes(start_time)
    end_min = time_to_minutes(end_time)
    return end_min > start_min


def validate_value_in_range(
    value: float | int,
    min_value: float | int,
    max_value: float | int,
) -> bool:
    """Validate that a value falls within the specified range (inclusive).

    Args:
        value: The value to check.
        min_value: The minimum allowed value.
        max_value: The maximum allowed value.

    Returns:
        True if the value is within [min_value, max_value], False otherwise.
    """
    return min_value <= value <= max_value


def clamp_value(
    value: float | int,
    min_value: float | int,
    max_value: float | int,
) -> float | int:
    """Clamp a value to the specified range.

    Args:
        value: The value to clamp.
        min_value: The minimum allowed value.
        max_value: The maximum allowed value.

    Returns:
        The clamped value.
    """
    return max(min_value, min(value, max_value))


def _slugify(text: str) -> str:
    """Convert text to a slug suitable for entity IDs.

    Converts to lowercase, replaces non-alphanumeric characters with
    underscores, and collapses multiple underscores.

    Args:
        text: The text to slugify.

    Returns:
        A slugified string.
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text


def _intervals_overlap(
    interval_a: tuple[int, int],
    interval_b: tuple[int, int],
) -> bool:
    """Check if two time intervals overlap.

    Both intervals are (start_minutes, end_minutes) where end > start.
    Intervals where end <= start are treated as zero-length or invalid
    and do not overlap with anything.

    Args:
        interval_a: First interval as (start, end) in minutes.
        interval_b: Second interval as (start, end) in minutes.

    Returns:
        True if the intervals overlap, False otherwise.
    """
    start_a, end_a = interval_a
    start_b, end_b = interval_b

    # Invalid intervals (end <= start) do not overlap
    if end_a <= start_a or end_b <= start_b:
        return False

    # Two intervals overlap if one starts before the other ends
    return start_a < end_b and start_b < end_a
