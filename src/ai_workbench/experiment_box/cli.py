"""UTF-8 CLI dispatch. Installation supplies config; business input cannot."""
import argparse
import json
from pathlib import Path
import sys

from .app import load_config
from .model import StoreError, TrialStore
from .service import ExperimentService, identifier


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise StoreError(message)


def dispatch(service, arguments, stdin):
    parser = JsonParser(prog="experiment-box-cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    for verb, field in (("show", "trial_id"), ("status", "request_id")):
        sub.add_parser(verb).add_argument(field)
    sub.add_parser("apply").add_argument("--json", required=True, choices=["-"])
    args = parser.parse_args(arguments)
    service.reload()
    if args.command == "list":
        return {"status": "read", "version": service.snapshot().get("revision", 0), "trials": service.trials()}
    if args.command == "show":
        trial = service.store._find(service.snapshot(), identifier(args.trial_id))
        return {"status": "read", "version": trial.get("revision", 1), "trial": trial}
    if args.command == "status":
        return service.status(args.request_id)
    raw = stdin.read(1_000_001)
    if len(raw) > 1_000_000:
        raise StoreError("请求超过 1 MB")
    return service.submit(json.loads(raw), origin="cli")


def run_bound(config_path, arguments=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        config = load_config(Path(config_path))
        root = Path(config["data_root"])
        result = dispatch(ExperimentService(TrialStore(root / "trials.json"), root),
                          sys.argv[1:] if arguments is None else arguments, sys.stdin)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] in ("read", "applied", "pending", "approved", "running", "finished", "cancelled") else 2
    except (StoreError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"request_id": None, "versions": {}, "summary": [], "status": "rejected", "error": str(error)}, ensure_ascii=False))
        return 2
