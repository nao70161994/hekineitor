"""Compatibility shim for engine.admin_reports."""
import sys as _sys
from engine import admin_reports as _module
from engine.admin_reports import *  # noqa: F401,F403
_sys.modules[__name__] = _module
