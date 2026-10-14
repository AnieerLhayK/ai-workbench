"""Cycles Module: derive work from durable successful coverage, never from attempts."""
from copy import deepcopy
from datetime import datetime, timedelta


class Cycles:
    def __init__(self, settings):
        self.settings = settings
        self.blocked = set()

    def due(self, at=None):
        at = at or datetime.now().astimezone()
        for kind, rule in self.settings.data["cycles"].items():
            if not rule["enabled"] or kind in self.blocked:
                continue
            anchor = datetime.fromisoformat(rule["anchor"])
            start = datetime.fromisoformat(rule["last_end"]) if rule["last_end"] else anchor
            deadline = (start + timedelta(days=rule["days"])).replace(hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0)
            if at >= deadline:
                # Preserve the configured wall-clock execution time after a delayed launch.
                end = at.replace(hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0)
                if end > at:
                    end -= timedelta(days=1)
                if end >= deadline:
                    return {"kind": kind, "start": start.isoformat(), "end": end.isoformat(), "automatic": True}
        return None

    def completed(self, request, success):
        if not request.get("automatic"):
            return
        kind = request["kind"]
        if success:
            rules = deepcopy(self.settings.data["cycles"])
            rules[kind]["last_end"] = request["end"]
            self.settings.update(cycles=rules)
        else:
            # No retry storm. User can retry explicitly; next app opening tries again.
            self.blocked.add(kind)
