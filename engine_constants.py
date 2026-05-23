"""Compatibility shim for engine.constants."""
import sys as _sys
from engine import constants as _module
from engine.constants import *  # noqa: F401,F403
_sys.modules[__name__] = _module
