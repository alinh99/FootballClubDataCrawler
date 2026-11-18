"""
Phase modules for v4 crawler.
"""

from .phase1 import process_phase1
from .phase2 import process_phase2

__all__ = [
    "process_phase1",
    "process_phase2",
]