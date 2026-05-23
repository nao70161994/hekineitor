"""Compatibility shim for engine.reporting."""
import sys as _sys
from engine import reporting as _module
from engine.reporting import *  # noqa: F401,F403
_sys.modules[__name__] = _module
