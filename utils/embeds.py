"""Хелперы для Discord embed."""

from __future__ import annotations

import config


def progress_bar(
    value: float,
    max_value: float,
    bar_length: int = 10,
    filled_char: str = "█",
    empty_char: str = "░",
) -> str:
    """Полоска прогресса (по умолчанию █ / ░)."""
    if max_value <= 0:
        return empty_char * bar_length
    percent = max(0.0, min(100.0, (value / max_value) * 100))
    filled = int(percent / (100 / bar_length))
    filled = max(0, min(bar_length, filled))
    return filled_char * filled + empty_char * (bar_length - filled)


def gray_progress_bar(
    value: float,
    max_value: float,
    bar_length: int = 10,
) -> str:
    """Серая полоска (как на панели сытости)."""
    return progress_bar(
        value,
        max_value,
        bar_length=bar_length,
        filled_char="▓",
        empty_char="░",
    )


def colored_progress_bar(
    value: float,
    max_value: float,
    bar_length: int = 10,
) -> str:
    """Полоска другого оттенка (для прочности)."""
    return progress_bar(
        value,
        max_value,
        bar_length=bar_length,
        filled_char="█",
        empty_char="▒",
    )


def status_emoji(
    percent: float,
    threshold_warning: float = config.WARNING_THRESHOLD,
    threshold_critical: float = config.CRITICAL_THRESHOLD,
) -> str:
    """Эмодзи статуса по проценту."""
    if percent <= threshold_critical:
        return "💀"
    if percent <= threshold_warning:
        return "⚠️"
    return "✅"
