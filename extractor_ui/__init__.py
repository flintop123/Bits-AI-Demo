"""Self-contained local UI for the ReAct extractor agent.

Everything for this feature lives in this package (blueprint, job runner and
static page). ``data_api.create_app`` mounts it with a single
``register_blueprint`` call; nothing else in the app is changed.
"""

from extractor_ui.api import EXTRACTOR_PREFIX, extractor_blueprint

__all__ = ["EXTRACTOR_PREFIX", "extractor_blueprint"]
