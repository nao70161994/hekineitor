"""Compatibility shim for engine.compound_works."""
import sys as _sys
from engine import compound_works as _module
from engine.compound_works import *  # noqa: F401,F403
_sys.modules[__name__] = _module
