"""The Flask console on the Vault's own screen.

Routes and template context only. The console renders plain-language data from
the backend modules and never re-derives detection or recovery logic.
"""

from .app import create_app

__all__ = ["create_app"]
