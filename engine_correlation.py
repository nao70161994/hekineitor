"""Compatibility shim for engine.correlation."""
import sys as _sys
from engine import correlation as _module
from engine.correlation import *  # noqa: F401,F403
_sys.modules[__name__] = _module
