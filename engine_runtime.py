"""Compatibility shim for engine.runtime."""
import sys as _sys
from engine import runtime as _module
from engine.runtime import *  # noqa: F401,F403
_sys.modules[__name__] = _module
