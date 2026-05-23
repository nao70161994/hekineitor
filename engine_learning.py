"""Compatibility shim for engine.learning."""
import sys as _sys
from engine import learning as _module
from engine.learning import *  # noqa: F401,F403
_sys.modules[__name__] = _module
