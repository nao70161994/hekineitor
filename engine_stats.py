"""Compatibility shim for engine.stats."""
import sys as _sys
from engine import stats as _module
from engine.stats import *  # noqa: F401,F403
_sys.modules[__name__] = _module
