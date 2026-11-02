"""Provider-neutral speech-to-text API support."""

__version__ = "0.1.0"

# This in-repository component shares configuration and accounting with cleanup.
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
