import pathlib
import sys

_parent = str(pathlib.Path(__file__).resolve().parent)
if _parent not in sys.path:
    sys.path.insert(0, _parent)
