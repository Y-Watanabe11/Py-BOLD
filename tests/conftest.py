"""pytest conftest — adds src/ to sys.path for all test modules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
