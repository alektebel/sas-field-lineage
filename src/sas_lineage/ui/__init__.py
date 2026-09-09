"""
UI module initialization

The Streamlit app (``app.py``) is an optional dependency, so importing this
package must not require ``streamlit``. The web explorer (``server.py``) is
self-contained and only needs the standard library.
"""
from . import payload  # noqa: F401
from . import trace   # noqa: F401

try:
    from .app import main
except ImportError:  # streamlit not installed — web explorer still works
    def main():
        raise RuntimeError(
            "Streamlit is not installed. Run the web explorer with "
            "`python -m sas_lineage.ui.server` instead."
        )

__all__ = ["main", "payload", "trace"]
