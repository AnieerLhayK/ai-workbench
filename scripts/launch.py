"""Portable source launcher; installed shortcuts pass their external config."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    from ai_workbench.app import main
    sys.exit(main((["--demo"] if args.demo else ["--config", str(args.config)])))
