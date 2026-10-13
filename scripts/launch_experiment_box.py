"""Portable native source launcher, with no host path assumptions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if __name__ == "__main__":
    from ai_workbench.experiment_box.app import main
    raise SystemExit(main())
