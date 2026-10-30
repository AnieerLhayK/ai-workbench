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
directory, existing Codex executable, optional custom prose file, user-style synchronization source, approved
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

ChatGPT JSON decoding is shared with independent local consumers through the
pure `ai_workbench.chatgpt_export` Module (`parse_chatgpt_export` and
`read_chatgpt_export`). It imports no Qt, account configuration or diary state
and writes nothing. It preserves message roles, branch links and current_node;
research callers decide selection themselves. e-Diary retains its existing
mapping-import user/assistant scope, local file-hash deduplication and storage.
Parsed content is private, not anonymized. Malformed/non-text records receive
coded diagnostics instead of becoming fabricated prose.
Import metadata retains these diagnostics, and evidence collection includes a
coverage warning whenever an import omitted malformed or non-text content.
The warning survives application reload and duplicate-import suppression.

Optional `personal_archive_root` identifies an owner-authorized private archive.
The native settings page can set or clear it. Personal reviews query confirmed
records by default; topic packages use an explicit **使用已确认个人档案** checkbox.
Development/work reviews do not read the archive. Demo never opens it.
The shared `personal_archive` Module validates and retrieves registered Markdown
without executing archive code or following links. Missing, malformed, stale
confirmation and budget limits remain coverage warnings. Current self-report
takes precedence; older archive entries are dated background, and interpretation
never becomes objective fact through confirmation. Adopted IDs, content hashes,
applicability dates and necessary excerpts remain in private report evidence.
Opted-in topic packages retain these fields and source snapshots in the
application-generated `个人档案依据.json`; it is reserved against model file names.
No generation writes candidates or synchronizes Git.

For standalone archive maintenance, `personal-archive` (or
`scripts/run_personal_archive.py`) provides `validate`, `query`, `review-digest`
and guarded `push-private`. Owner approval is a maintenance obligation; the
content digest checks the reviewed version, not the owner's identity. Archive
locations and repository identities belong in external configuration, never
portable source. The reader caps files at 256 KiB, scanned entries at 2,000 and
input at 16 MiB; adopted context is at most 20 entries / 12,000 characters and
reserves space within the existing 180,000-character evidence budget.

Manage source roots in **资料来源**. A single-project source reads bounded Git
activity and selected changed text files. A collection discovers immediate Git
children only. It does not recursively inventory the whole workspace or projects
tree. Archive/dependency/build paths and links are excluded. Current file text and
uncommitted status provide context, not proof that work was completed in a period.

A **普通目录（工作资料）** source also accepts a non-Git research folder. Its first
registration captures existing UTF-8 text and PPTX content fingerprints as background;
only later new or changed content becomes delayed evidence in a work summary.
Saving an unchanged registration preserves that baseline and successful coverage.
Moving a source or changing its mode establishes a new baseline. The scan does not
follow links, visits at most 2,000 entries / 200 accepted files, reads at most 8 MB
per file and 16 MB per scan, and extracts bounded slide and notes text from PPTX.
DTD/entity XML and damaged presentations are rejected with coverage warnings;
images are not interpreted as experimental results.

A dedicated 40,000-character laboratory slice precedes general session evidence.
Changed material takes priority over unchanged background. A successful normal
work summary acknowledges only adopted file versions; failure, cancellation and
comparison generation leave coverage unchanged. Missing or truncated material
leaves warnings. Discovery/update time is not the date of the experiment: a report
must identify material that concerns earlier work or whose activity date is unknown.

Development/work summaries follow coherent work threads, results, unfinished or
shelved work, broad implementation ideas and significant technical decisions.
They use bounded prior diary and report context (up to 180 days, 20 diaries and
8 same-type reports, 24,000 characters) to understand continuing priorities;
generated history is background rather than independent factual proof. Experience
and attitude follow the user's own descriptions. Conservative inferences from
diaries are qualified; specific outcomes and metrics require direct evidence.
The body normally has 600–2,000 non-whitespace characters, may be shorter when
materials are insufficient, and remains within 2,000 for merged periods too.
Technical inventories, commands and test counts belong in evidence, not the body.

**生成对比版** creates a separate development/work summary for the same period,
retains the original, and advances neither cycle nor directory coverage. Existing
**重新生成** retains its revision-based editing behavior. Compare actual reports
before accepting a new writing workflow; mechanical tests do not establish prose quality.

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

Every real generation rereads the selected prose file. Optional **user-style** uses
an independent private mirror under `data_root/user-style`, never the external
source directly. Settings shows the source, mirror availability and last sync.
Save the source directory, then click **同步 user-style** to accept updates.
Opening or generating never synchronizes. The existing `zf_root` configuration
key remains a compatible synchronization-source setting, and installer
`-UserStyleSource` accepts the old `-ZfRoot` alias.

Synchronization copies SKILL.md and its recursively referenced text resources
from references/prompts, excluding raw corpus and maintenance artifacts. A bounded,
validated immutable snapshot is committed by one atomic pointer replacement.
Failure preserves the previous mirror. Each generation reads one snapshot and
records resource fingerprints. Editing a mirror invalidates it; change the source
and explicitly synchronize instead. No junction or character-system write is
needed. Initial personal generation requires the first manual sync; missing
resources stop generation with an actionable error. Personal reviews enable
user-style by default; other tasks retain an explicit option.

User facts, evidence and requested formats take precedence over style. Personal
reviews have their own writing requirements: address the reader as "you", with
warmth and honesty, connecting a few important experiences rather than listing
days or measuring life through work output. Relationships, interests, rest, joy,
conflicting feelings and unresolved concerns can each be a main thread when
supported by the records. Interpretations must remain grounded and open to the
reader's disagreement; no diagnosis, personality labels or invented feelings.
Do not turn fatigue into compulsory growth or replace understanding with generic
reassurance. Advice is optional, brief and never a fixed action checklist.

Personal evidence uses the existing 180000-character task budget in this order:
current diaries and dated imported user messages, bounded historical background,
then auxiliary material such as development/work reports and assistant messages.
Earlier feelings are not evidence of the current state. Generated reports and
assistant messages cannot independently prove the user's feelings, motives or
achievements. History covers the previous 180 days, up to 20 diaries and 8 personal
reviews, with a combined 24000-character ceiling and at most 2400 per record.
Source roles, periods and omitted/truncated material remain visible in the
evidence; explain material limitations briefly rather than throughout the prose.
Personal tasks do not scan registered project sources or Codex sessions.

Normal personal prose is 600–2000 characters; insufficient evidence may produce a
shorter response with a brief explanation. There is no enforced minimum; bodies
over 2000 non-whitespace characters are rejected before saving, including merged
catch-up periods. A style snapshot controls expression, not these requirements.
Personal reviews retain the existing generation controls and scheduling.
Automated checks use synthetic evidence without changing private coverage;
actual narrative quality remains a separate user assessment.

## Topic packages

Built-in topics are awards, party affairs, research meetings and course completion.
**管理主题** edits goals/boundaries and default prompts, adds new topics or removes
them without deleting previous packages. Select dates, diary/development/work
sources, an optional user-style mode, supplementary files and an output directory. Prompts
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
Saved reports retain pending coverage bookkeeping if settings persistence fails.
Reopening or submitting again retries that acknowledgement against the saved
entry, without regenerating the same automatic report.

Run `tests/test_e_diary.py` and the complete package suite with staging-backed
temporary directories. Verify diary recovery/conflicts, source timing/branching,
loop coverage and cancellation, live style updates, binary outputs and native
interactions. Review native screenshots against the accepted concepts in both
themes, at small sizes and display scaling; browser QA does not apply to Qt.
Real Codex calls and local deployment require their approved host task. Export
only portable source/tests/docs and placeholders; exclude diaries, imports,
configuration, credentials, task scratch and private style resources. The generic
bundled prose discipline is an explicitly approved public application resource.
