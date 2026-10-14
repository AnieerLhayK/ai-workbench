"""Portable native source launcher; configuration and data stay external."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if __name__ == "__main__":
    from ai_workbench.e_diary.app import main
    raise SystemExit(main())
