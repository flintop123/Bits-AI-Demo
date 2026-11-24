"""Agentic, provenance-first ingestion components.

This package is intentionally separate from the existing ReAct layer in
``agent.py``.  It provides structured contracts and an auditable ingestion
pipeline that can be reviewed independently before any integration decision.
"""

from ingestion_v2.models import (
    IngestionRun,
    SourceModality,
    TargetCollection,
)

__all__ = ["IngestionRun", "SourceModality", "TargetCollection"]
