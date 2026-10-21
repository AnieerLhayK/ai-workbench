# e-Diary

e-Diary is an independent native Qt application for text diaries, development and
work summaries, personal reviews and topic-specific evidence packages. It calls
the existing local Codex CLI directly; Pi and API keys are not required.

Writing generation shares the package's tool-free Codex isolation policy with
e-Chatter and the experiment assistant. It ignores user configuration and rules,
disables tools/integrations, and uses an app-owned restricted model catalog.
Unsupported isolation stops before submitting evidence; there is no permissive
fallback. Authentication stays in Codex. History reading retains its separate
transport and does not acquire generation or execution authority.

## Start

Use the package's existing Python 3.13 / PySide6 6.9.2 environment:

```powershell
python -B scripts/launch_e_diary.py --demo
python -B scripts/launch_e_diary.py --config <external-config.json>
```

Installed environments also expose `e-diary --demo` / `e-diary --config ...`.
Copy `examples/e-diary.config.example.json` outside source and replace its
placeholders with absolute paths. Configuration identifies the private data
directory, existing Codex executable, optional custom prose file, live zf directory, approved
staging directory and two initial source roots (one Git project and one collection
of immediate child Git projects). The first real opening is empty; demo remains
in memory and never reads real sessions, source roots or style resources.

`scripts/Install-EDiary.ps1` accepts explicit runtime, style, staging, source and
desktop paths. It creates external configuration and a desktop shortcut, refuses
existing targets and installs no dependencies. Generate the owned icon with
`python -B scripts/make_icon.py --name e-diary` before deployment.

## Diaries and reading

Create several entries on the same date, edit dates, titles, tags and body, and
choose Markdown or plain text. Search matches Chinese text and tags; the date
selector filters months. Text autosaves after a short pause. Summaries have a
period history list and built-in reader/editor, with source excerpts and optional
record-count charts. No external editor is necessary to read a generated review.

Each stable entry directory holds `record.json` and UTF-8 `.md` / `.txt` revisions.
The descriptor points to the committed current text. A failed descriptor write
leaves the previous version readable. The in-memory search index rebuilds from
descriptors and text on opening/querying; there is no authoritative database.
Editing a current text file externally reloads on activation. Concurrent changes
stop autosave and offer external reload or a separate diary copy. Historical
versions restore as a new revision. Each revision snapshots its own tags, period,
evidence, chart and style metadata; restoration does not attach a later
generation's sources to an earlier body. Deletion is a reversible descriptor
flag; permanent deletion requires an explicit confirmation in the recycle bin.

## Sources and generation

Manage source roots in **资料来源**. A single-project source reads bounded Git
activity and selected changed text files. A collection discovers immediate Git
children only. It does not recursively inventory the whole workspace or projects
tree. Archive/dependency/build paths and links are excluded. Current file text and
uncommitted status provide context, not proof that work was completed in a period.

Codex history, including archived threads, uses app-server `thread/list` and paginated `thread/turns/list` without
resuming sessions. Missing/incompatible history interfaces appear in coverage
warnings; the application does not guess a private database format. Explicit
source kinds include desktop app-server conversations. e-Diary generation is
ephemeral, and returned task thread IDs are also excluded from future collection.

Import a ChatGPT export ZIP containing `conversations.json`, a JSON export or a
single Markdown/text conversation. Mapping-node parent/children links retain
branch structure. Identical files are not reimported. JSON `messages` and `body`
forms are supported. Undated imports are identified as background, never assigned
an invented activity date. Collection has bounded file/page/character budgets;
coverage warnings accompany summaries and exported packages.

The three loops default on after configuration: development/work every seven
days, personal review every twenty-one. Each has an independent switch and day
interval (days or weeks in the UI). Execution defaults to local 09:00 and runs only while the application
is open. The first event-loop turn after opening checks immediately; completion
checks the next type immediately, and a fifteen-second timer also checks for
newly due work. Development, work and personal reviews run serially in that
order. Missed intervals of each type merge into one request from its last
successful coverage to the most recent configured daily execution time. For
example, opening at October 23 14:00 after missing October 21 09:00 covers through
October 23 09:00; a seven-day cycle next falls on October 30 09:00.

A status area above every page shows each type's coverage, waiting/generation
state, failure and completed report link. Completion does not change pages or
interrupt diary editing. Links remain for this opening; older reports remain in
their respective sections. Opening a link first saves current edits, then clears
list filters and selects that exact report. A failed save keeps the current page.
This is an in-app status area, not a background service or system notification.

Failure/cancellation never advances coverage and pauses that type for the current
opening while other types continue. Both the status area and cycle settings offer
per-type retry, disabled while any generation is running. Retry derives a fresh
request from that type's current successful coverage, never the last other task.
Settings changes or reopening also allow automatic attempts again. Closing during
a generation cancels it before exiting and cannot start the next queued type.

The general prose discipline is maintained in `src/ai_workbench/e_diary/prose.md`
and shipped in source projections and installed Python packages. It was imported
from the user-authorized external prose document; this tracked copy is now the
application default and is maintained with its source. Leave `prose_path` empty
to use it; an explicit absolute path selects a custom live file instead. Missing
custom files fail rather than silently changing the requested discipline. The
installer no longer requires an external prose file. Private character resources
remain external and are not bundled.

Every real generation rereads the selected prose file and, when enabled, the zf skill and
its selected references. Personal reviews enable zf by default; other tasks offer
an explicit option. Resource fingerprints are audit metadata rather than a pinned
style version. Missing required resources stop the task. User facts, evidence and
requested formats take precedence over style. Personal reviews emphasize the
user's own diary descriptions of mood and motivation, avoid diagnosis and invented
mood scores, and do not force a diary percentage or a standard advice section.

## Topic packages

Built-in topics are awards, party affairs, research meetings and course completion.
**管理主题** edits goals/boundaries and default prompts, adds new topics or removes
them without deleting previous packages. Select dates, diary/development/work
sources, an optional zf mode, supplementary files and an output directory. Prompts
have no arbitrary 500-character limit. A quoted absolute path or a standalone
absolute-path line authorizes additional material for that task only; directories
contribute immediate text children, not recursive scans. Use the registry to grant
ongoing access separately.

Every package is delivered to a unique task subdirectory after validation. A body
and evidence index are always provided; requested Markdown, text, CSV, JSON, HTML,
PDF and source-backed PNG/SVG charts can be added. HTML is escaped; PDF is rendered
from Markdown; charts use actual diary counts rather than model-supplied numbers.
The app previews text, images and PDF and retains a report history. Office file
formats are outside this first version. File names cannot escape the package and
existing deliveries are never overwritten.

e-Diary does not filter private content and has **no desensitization capability**.
Before external presentation it reminds the user to use other tools; it never
claims a package has been desensitized.

## Maintenance and acceptance

The DiaryLibrary, Sources, GenerationJobs, Cycles and Reports Modules own their
respective behavior. Windows only compose and observe them. Real, demo and
controlled generation Adapters cross the same Interface. Worker results return
through Qt signals; provider output is not persisted as a diagnostic log.

Run `tests/test_e_diary.py` and the complete package suite with staging-backed
temporary directories. Verify diary recovery/conflicts, source timing/branching,
loop coverage and cancellation, live style updates, binary outputs and native
interactions. Review native screenshots against the accepted concepts in both
themes, at small sizes and display scaling; browser QA does not apply to Qt.
Real Codex calls and local deployment require their approved host task. Export
only portable source/tests/docs and placeholders; exclude diaries, imports,
configuration, credentials, task scratch and private style resources. The generic
bundled prose discipline is an explicitly approved public application resource.
