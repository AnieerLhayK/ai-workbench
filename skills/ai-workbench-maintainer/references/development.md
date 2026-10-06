# Development workflow

1. Inspect Git state and ownership. In Workspace resolve/register the host task;
   standalone clones follow their own task/permission rules without Workspace CLI.
2. Read affected controller, adapter and UI callers. Keep async complexity inside
   the controller/adapter; start/stop/state observation is the public interface.
3. Add focused tests using a controlled adapter. Cover pending requests, late
   completion, failure recovery and independent tools where behavior changes.
4. Run existing pytest and QtTest with temporary output in approved staging.
   Use Python 3.13+ / PySide6 6.9.2, with declared dependencies in a dedicated
   environment for standalone development. No global dependency
   installation is part of ordinary development.
5. For GUI changes launch a native window. Review five collapsible categories,
   scrolling, empty hints, header focus/status and themes at normal and minimum
   size. Expand the two launcher groups, toggle start/stop, observe waiting animation and
   independently disabled requests. Check failure text with a controlled adapter. Browser checks are
   not applicable to this native application.
   For terminal changes also review the shared project selector and both
   new/resume buttons. Verify independent pending/error behavior and command
   snapshots through a controlled Adapter; demo must not open a terminal.
   Real acceptance requires configured local process authority and leaves
   task submission, trust and login to the user in the visible CLI.
   Verify hidden rows keep observing, and theme/expansion preferences merge
   without service requests. Existing local deployment acceptance observes
   services while closing/reopening only the GUI; no service restart is needed.
6. Review final-state instructions, launchers, dependencies and export contract.
   Record actual evidence in the host task; remove successfully used transients
   under its cleanup policy. Follow host Git delivery rules.

Adapter completion and observations run on the GUI thread. Real control uses
the detached-worker file seam; do not block GUI callbacks with shell commands.
Verify process identity, duplicate detection, timeout, interrupted requests and
window-independent operation through the control Module Interface.
