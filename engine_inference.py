"""Compatibility shim for engine.inference."""
import sys as _sys
from engine import inference as _module
from engine.inference import *  # noqa: F401,F403
_sys.modules[__name__] = _module
