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
]
