"""Compatibility shim for engine.db."""
import sys as _sys
from engine import db as _module
from engine.db import *  # noqa: F401,F403
_sys.modules[__name__] = _module
