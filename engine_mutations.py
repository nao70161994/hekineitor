"""Compatibility shim for engine.mutations."""
import sys as _sys
from engine import mutations as _module
from engine.mutations import *  # noqa: F401,F403
_sys.modules[__name__] = _module
