"""Presentation helpers for queue timing."""

from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def asset(path):
    """Return a static URL with an mtime cache-buster.

    Browsers otherwise keep serving a previously cached stylesheet/script after
    the source changes; appending the file's modification time forces a refresh.
    """
    url = static(path)
    absolute = finders.find(path)
    if absolute:
        try:
            stamp = int(Path(absolute).stat().st_mtime)
        except OSError:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}v={stamp}"
    return url


@register.filter
def wait_label(seconds):
    """Render a seconds value as a friendly, clearly approximate label."""
    if seconds is None:
        return "—"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds <= 0:
        return "now"
    if seconds < 90:
        return "~1 min"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"~{minutes} min"
    hours = minutes / 60
    return f"~{hours:.1f} h"


@register.filter
def duration_label(seconds):
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60}m"
