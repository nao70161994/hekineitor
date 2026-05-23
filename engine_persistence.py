"""Compatibility shim for engine.persistence."""
import sys as _sys
from engine import persistence as _module
from engine.persistence import *  # noqa: F401,F403
_sys.modules[__name__] = _module
