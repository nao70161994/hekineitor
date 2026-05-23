"""Public engine package facade.

The implementation source lives in `engine/facade.py`, but it is executed in this
package namespace so historical patch points such as `engine._use_db` and
`engine.threading.Thread` keep affecting `Engine` method globals.
"""

from pathlib import Path as _Path
import sys as _sys

_facade_path = _Path(__file__).with_name('facade.py')
exec(compile(_facade_path.read_text(encoding='utf-8'), str(_facade_path), 'exec'), globals())
_sys.modules[__name__ + '.facade'] = _sys.modules[__name__]
facade = _sys.modules[__name__]
