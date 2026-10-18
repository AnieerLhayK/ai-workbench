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
changes. QtTest exercises native controls. e-Chatter's embedded React interface
additionally requires browser interaction checks before native bridge checks.
Always distinguish simulated evidence from actual service readiness. The native
window groups tools using the portable read-only Catalog Module. ChatGPT owns
Commander, Hermes owns Hermes Bot; Claude and Codex provide project terminal
actions, and OpenCode has no launcher. Catalog holds launcher collections with
explicit service/terminal kinds. Collapse only hides presentation: keep one
Controller per service launcher and continue
observing hidden rows and header summaries. Theme and expansion settings persist externally and must
not issue service commands; do not add a theme keyboard shortcut.

Merge preference changes with the current external document, retaining unrelated
fields. Distinguish an absent/malformed expansion list (default ChatGPT/Hermes)
from an empty list (all collapsed); ignore unknown IDs. Keep this regression
coverage when adding preferences. Package registration must not read private
host platform manifests at runtime or from an independent preview.

For terminal changes load [project terminals](../docs/project-terminals.md).
The TerminalLauncher Module owns dispatch state behind launch/observe; Windows,
demo and controlled Adapters share its Seam. Terminal dispatch is independent
of service lifecycle: do not report Agent readiness or invent a stop control.
Snapshot the selected directory per request, use literal paths and fixed CLI
arguments, and merge selected/recent project preferences externally. Detached
terminal brokers survive window closure. A successful broker exit verifies
handoff only; CLI errors and permissions remain visible in the terminal.

Read [local controls](../docs/local-controls.md) for detached workers, process
identity, timeouts, connection semantics and local deployment. Observed process
state is authoritative; never treat a stale PID or installer as a ready device.

## Storage and dependencies

`codex_isolation` owns generation-only capability restrictions for e-Diary,
the experiment assistant and e-Chatter. Keep policy/catalog/event checks shared,
but preserve the two transports and their domain errors. Empty TOML maps merge
with inherited entries: app-server must disable discovered MCP entries and
verify readback before a model thread. Do not apply generation restrictions to
the generic history/approved-experiment transport. Attachment limits must bound
expanded bytes as well as compressed files, before parsing or registering data.

For e-Diary follow [its storage and generation contract](../docs/e-diary.md).
Treat the entry descriptor as the text revision commit point. The previous
revision must remain readable when saving fails. Keep generation work off the
GUI thread and marshal completion through signals; a cancelled or duplicate
completion must not publish or advance cycle coverage. Rebuild search state from
private files; do not make an index the only owner of diary content. Generated
reviews and source-backed charts are read in-app, with live style resources
resolved for each task rather than bundled into the public projection.

For the independent Personal Experiment Box read [experiment-box](../docs/experiment-box.md).
Its normal data starts empty; demo data remains memory-only. Never reuse the
service-control config loader for trial storage. UI, CLI and assistant use
ExperimentService. Critical proposals require native human approval; untrusted
JSON cannot approve, run or invoke the manual terminal. Verify actual native
read/write/network/child restrictions before offline execution. Unsupported
isolation stops without fallback. Malformed records stop without overwrite;
failed writes keep both draft UI values and the previous committed snapshot.
Confirm the complete user command and resolved directory before handing an
immutable snapshot to the terminal Module. Handoff never establishes trial success.

In Workspace use the existing approved Python/Qt runtime. Standalone clones may
install declared dependencies in a dedicated environment under their host rules.
Keep the tested PySide6 version
pinned. Changing dependency storage requires the host storage governor's
audit → plan → verify workflow, not an incidental global pip command.
Source, example configuration and durable docs stay here. Screenshots, test
temporary files and preview output use host staging; remove transients after
successful use. Future runtime state and credentials belong in an approved
external data directory, not a public export.

When closing a trial window, disconnect terminal observers and widget-capturing
callbacks before Qt teardown. Cancel/join generation and retain failed-save results
for an explicit save retry; retrying must reuse the original operation ID. Approved
detached scripts keep their own lifecycle and actual interruption/output receipts.
Block window closure while an assistant save retry remains pending. A process-held
per-request lock identifies live workers; missing workers become interrupted
receipts with unknown output/exit code, never fabricated results or automatic retries.

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

For e-Chatter, configuration map overrides may merge with the user's Codex
configuration. An empty MCP map does not prove isolation. Before any model thread,
read effective settings, disable each discovered MCP entry, restart and verify
all entries disabled along with execution features. Keep provider diagnostics
limited to safe categories, never raw account/configuration dumps.
