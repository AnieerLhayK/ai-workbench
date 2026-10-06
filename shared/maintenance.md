# Maintenance contract

## Scope and authority

Ordinary development owns package source, tests and portable docs. Registered
host governance retains task records, catalogs, publication and tool authority.
The application provides configured real local controls and an explicit demo.
Real process control, local deployment, authorization, credential access,
external installation, cleanup and publication require their own authorized task.
A skill or MCP connection does not grant those permissions.

## Design and evidence

The lifecycle module owns state transitions and async completion. Its adapters
complete on the controller's thread; a future worker adapter must marshal its
completion to the GUI thread. The UI observes state and sends requests. Each
tool has its own controller. Pending requests reject reentry; failure retains
the last confirmed running state. No speculative plugin framework is needed.

Complete code changes with relevant lifecycle and Qt interaction tests, native
window review for GUI changes, and portable preview verification for export
changes. QtTest exercises native controls; browser testing is not applicable.
Always distinguish simulated evidence from actual service readiness. The native
window groups tools using the portable read-only Catalog Module. ChatGPT owns
Commander, Hermes owns Hermes Bot; Claude, Codex and OpenCode have no launcher.
Collapse only hides presentation: keep one Controller per launcher and continue
observing hidden rows and header summaries. Theme and expansion settings persist externally and must
not issue service commands; do not add a theme keyboard shortcut.

Merge preference changes with the current external document, retaining unrelated
fields. Distinguish an absent/malformed expansion list (default ChatGPT/Hermes)
from an empty list (all collapsed); ignore unknown IDs. Keep this regression
coverage when adding preferences. Package registration must not read private
host platform manifests at runtime or from an independent preview.

Read [local controls](../docs/local-controls.md) for detached workers, process
identity, timeouts, connection semantics and local deployment. Observed process
state is authoritative; never treat a stale PID or installer as a ready device.

## Storage and dependencies

In Workspace use the existing approved Python/Qt runtime. Standalone clones may
install declared dependencies in a dedicated environment under their host rules.
Keep the tested PySide6 version
pinned. Changing dependency storage requires the host storage governor's
audit → plan → verify workflow, not an incidental global pip command.
Source, example configuration and durable docs stay here. Screenshots, test
temporary files and preview output use host staging; remove transients after
successful use. Future runtime state and credentials belong in an approved
external data directory, not a public export.

Application creation selects the loaded Qt runtime's platform plugin directory
through an application argument. Keep plugin selection local to the application;
global Qt/Python configuration repairs belong to a separately authorized task.

## Projection and maintenance lesson

An explicit export contract separates portable code from host registrations.
Tests must run from the exported directory so accidental host dependencies are
detected. Do not add host TASKs, catalogs, credentials or machine paths to the
contract. Keep the host's existing public template exclusion separate from this
local preview. Own public content is MIT and has independent projection history.
Official updates use the registered Workspace publisher; external contributions
return to Workspace for review. A standalone clone can develop and run simulated
tests without host governance. The generated source marker contains only package,
relative source path and Workspace commit; it never carries private host URLs.

Run projection tests in an independent export as well as source. Provenance
preservation means a public clone is a different fixture from an unmarked source
tree; tests must explicitly create null markers when exercising local previews.

Maintain documentation against final behavior: a controller failure is not a
stopped service; a simulated start is not device authorization. These two
distinctions must survive future adapter changes.

When a provider exits, preserve a safe error category and exit code before
finishing the request. Drain its final output so process polling does not race
the reader. Keep classification tests that include private data, and assert
that raw provider output never reaches state files or logs.

Validate every distinct provider dependency in a connection diagnosis. A working
public entry endpoint does not prove its session/database backend is reachable.
Test inherited proxy behavior through the actual child launch boundary, keep
network changes local to that child, and preserve explicit user overrides.
