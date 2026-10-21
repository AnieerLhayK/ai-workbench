"""Cycles Module: derive work from durable successful coverage, never from attempts."""
from copy import deepcopy
from datetime import datetime, timedelta


class Cycles:
    def __init__(self, settings):
        self.settings = settings
        self.blocked = set()

    def overview(self, at=None):
        """Ordered cycle snapshots shared by scheduling and every presentation."""
        at = at or datetime.now().astimezone()
        result = []
        for kind in ("development", "work", "personal"):
            rule = self.settings.data["cycles"][kind]
            anchor = datetime.fromisoformat(rule["anchor"])
            start = datetime.fromisoformat(rule["last_end"]) if rule["last_end"] else anchor
            deadline = (start + timedelta(days=rule["days"])).replace(hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0)
            request = None
            if rule["enabled"] and at >= deadline:
                # Preserve the configured wall-clock execution time after a delayed launch.
                end = at.replace(hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0)
                if end > at:
                    end -= timedelta(days=1)
                if end >= deadline:
                    request = {"kind": kind, "start": start.isoformat(), "end": end.isoformat(), "automatic": True}
            result.append({"kind": kind, "enabled": rule["enabled"], "next_due": deadline.isoformat(),
                           "blocked": kind in self.blocked, "request": request})
        return result

    def due(self, at=None):
        return next((row["request"] for row in self.overview(at)
                     if row["request"] and not row["blocked"]), None)

    def retry(self, kind, at=None):
        """Release only this failed automatic cycle, using its current coverage."""
        row = next((row for row in self.overview(at) if row["kind"] == kind), None)
        if row and row["blocked"] and row["request"]:
            self.blocked.discard(kind)
            return row["request"]
        return None

    def completed(self, request, success):
        if not request.get("automatic"):
            return
        kind = request["kind"]
        if success:
            rules = deepcopy(self.settings.data["cycles"])
            rules[kind]["last_end"] = request["end"]
            self.settings.update(cycles=rules)
            self.blocked.discard(kind)
        else:
            # No retry storm. User can retry explicitly; next app opening tries again.
            self.blocked.add(kind)
