"""Source-tree entry for the shared personal archive Module."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if __name__ == "__main__":
    from ai_workbench.personal_archive import main
    raise SystemExit(main())
