"""AbletonCtrl Remote Script entrypoint."""
import sys

sys.modules.setdefault("ableton_ctrl", sys.modules[__name__])
from .adapter.remote_script import create_instance  # noqa: E402

__all__ = ["create_instance"]
