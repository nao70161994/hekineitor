"""Compatibility shim for engine.data."""
import sys as _sys
from engine import data as _module
from engine.data import *  # noqa: F401,F403
_sys.modules[__name__] = _module
