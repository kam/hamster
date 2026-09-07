import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))


def pytest_configure():
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
