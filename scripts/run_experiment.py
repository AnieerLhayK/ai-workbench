"""Private detached Runner entry. Public CLI never dispatches this command."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_workbench.experiment_box.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
