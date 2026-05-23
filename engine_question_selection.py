"""Compatibility shim for engine.question_selection."""
import sys as _sys
from engine import question_selection as _module
from engine.question_selection import *  # noqa: F401,F403
_sys.modules[__name__] = _module
