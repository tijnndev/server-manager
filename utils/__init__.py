"""Compatibility shim to expose functions from the legacy utils.py module.

This package exists to hold helper submodules (e.g. discord.py), but the
project also has a top-level utils.py with commonly imported helpers like
find_process_by_name. When Python sees both a package directory and a module
file with the same name, the package wins, which broke imports such as
`from utils import find_process_by_name` in production. To keep backward
compatibility without renaming everything, we dynamically load the sibling
utils.py file and re-export its public symbols from this package.
"""

from importlib import util as _importlib_util
from pathlib import Path as _Path
from typing import TYPE_CHECKING  # noqa: F401
import sys as _sys

_base_module_path = (_Path(__file__).resolve().parent.parent / "utils.py")

if _base_module_path.exists():
	_spec = _importlib_util.spec_from_file_location("_utils_file", _base_module_path)
	if _spec and _spec.loader:
		_base_module = _importlib_util.module_from_spec(_spec)
		_sys.modules["_utils_file"] = _base_module
		_spec.loader.exec_module(_base_module)
		for _name in dir(_base_module):
			if not _name.startswith("_"):
				globals()[_name] = getattr(_base_module, _name)
		del _base_module
	del _spec

# Explicitly export submodules in this package
from .discord import DiscordNotifier, get_user_discord_settings  # noqa: F401,E402
from .performance import *  # noqa: F401,F403,E402
from .process_monitor import *  # noqa: F401,F403,E402

__all__ = [
	"DiscordNotifier",
	"get_user_discord_settings",
]

# Hint type checkers about dynamically exported symbols from utils.py
if TYPE_CHECKING:
	from _utils_file import get_domain_status  # type: ignore  # noqa: F401
