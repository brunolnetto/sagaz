# ============================================
# FILE: sagaz/visualization/__init__.py
# ============================================
"""
Visualization module for Sagaz - contains diagram generation utilities.

This module re-exports visualization components for backward compatibility.
"""

from sagaz.visualization.mermaid import (
    HighlightTrail,
    MermaidGenerator,
    StepInfo,
)

__all__ = [
    "HighlightTrail",
    "MermaidGenerator",
    "StepInfo",
    "create_app",
    "publish_event",
    "run_server",
]


def create_app(*args, **kwargs):
    """Lazy import create_app to avoid mandatory fastapi import."""
    from sagaz.visualization.server import create_app as _create_app

    return _create_app(*args, **kwargs)


def run_server(*args, **kwargs):
    """Lazy import run_server to avoid mandatory fastapi import."""
    from sagaz.visualization.server import run_server as _run_server

    return _run_server(*args, **kwargs)


def publish_event(event) -> None:
    """Lazy import publish_event."""
    from sagaz.visualization.server import publish_event as _publish_event

    _publish_event(event)
