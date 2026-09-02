"""Хелперы для Discord embed."""

from __future__ import annotations

import config


def progress_bar(value: float, max_value: float, bar_length: int = 10) -> str:
    """Полоска прогресса из █ и ░."""
    if max_value <= 0:
        return "░" * bar_length
    percent = max(0.0, min(100.0, (value / max_value) * 100))
    filled = int(percent / (100 / bar_length))
    filled = max(0, min(bar_length, filled))
    return "█" * filled + "░" * (bar_length - filled)


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
