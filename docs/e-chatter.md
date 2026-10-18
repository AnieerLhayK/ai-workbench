# e-Chatter v1

e-Chatter is a local Windows character chat, diagnosis and revision application.
It ships no personal characters. Each person uses their own Codex installation,
official login and local library. There is no application account or cloud sync.

## Run

Extract the Windows x64 portable ZIP and open `e-Chatter.exe`. Python and Node
are included or unnecessary at runtime; install Codex separately. In Settings,
select an existing Codex executable if it is not on PATH, then connect/login.
Use the character manager to import a character folder containing `SKILL.md`,
confirm its type and choose developing/runtime. New sessions start without a role.

The default library is `%LOCALAPPDATA%/ai-workbench/e-chatter`. This Workspace
host can pass an explicitly approved external directory with `--data`. Changing the character
directory does not move or delete the old directory. Themes persist in Settings.
`--demo` uses synthetic memory-only examples and never loads the real library.

## Chat and revisions

Generator and Maintainer require confirmation. Their conversations are separate
engineering tasks; finish or cancel to return to role chat. Doctor diagnoses the
latest character response, or a response selected from its message action.
Diagnostics record the exact character version and can supply a maintenance
handoff. Saving an adjusted version does not establish that its behavior improved.
For an explicitly provisional evaluation without a confirmed character response,
type `@doctor --provisional <text>`. Its saved record is permanently marked as
unconfirmed and cannot establish a character version's runtime behavior.

Original imports and writing materials are read-only. Proposed changes are
written under task-specific staging, reviewed, then accepted as new app-owned
versions. A conflicting or externally changed version cannot be overwritten.
Ordinary use supports chat/writing/read-only work; software development, generic
terminals and arbitrary scripts are outside the application. Temporary skills
may be attached or referenced as `@"<absolute-local-path>/SKILL.md"`; they add no permissions.

DOCX attachments have both a 16 MB compressed-file limit and a 16 MB expanded
`word/document.xml` limit. Oversized or damaged documents are rejected as a
whole; split the original and import again. The application never truncates or
registers a partially read attachment. DTD/custom entity declarations are rejected
before XML tree parsing, including declarations in UTF-16 documents.

Generation uses the package's shared Codex isolation policy. Tool-free model
catalogs and disabled execution/integration features are required. The desktop
app-server verifies effective feature/MCP settings before a model thread starts;
unsupported or ineffective isolation blocks generation. Official authentication
remains in Codex, and the application does not modify the user's Codex settings.

Export/import in Settings migrates sessions, folders, character versions,
diagnostics, handoffs and committed documents. Preview precedes import; imported
IDs are remapped without overwriting existing entries. Credentials, staging and
external source corpora are excluded. Libraries do not follow Codex account changes.

## Build and verification

Use Python 3.13 and the declared PySide6/PyYAML dependencies. Run `npm ci` and
`npm run build` in `frontend/e-chatter`, then launch `python scripts/launch_e_chatter.py --demo`.
Browser preview requires `npm run dev` and the explicit `?demo=1` query.
Its in-memory provider is not evidence of actual Codex readiness.

Install PyInstaller 6.22.3 into a dedicated build environment and run
`python scripts/build_e_chatter.py --staging <external-build-dir> --output <external-release-dir>`.
The builder bundles QtWebEngine, the built frontend and application-adapted
engineering resources. It does not bundle Codex or any imported character.
Retain all Qt and other third-party license files with the portable directory.

Run `python -B -m pytest -q -p no:cacheprovider --basetemp <external-test-dir>`.
Verify frontend interactions in a browser, then the real Qt WebChannel and frozen
desktop build. Real Codex checks use official managed authentication and synthetic
prompts; never copy login credentials into test fixtures or migration archives.

Native WebEngine checks run separately from offscreen QWidget/PDF tests. In a
desktop PowerShell set `$env:E_CHATTER_RUN_NATIVE='1'` and
`$env:QT_QPA_PLATFORM='windows'`, then run only `tests/test_e_chatter_qt.py` in a
fresh Python process. The ordinary simulated suite explicitly skips this check.
On some Windows Qt/COM installations pytest logs a handled accessibility exception;
assert the actual DOM/bridge outcomes and process result, and inspect the window.

## Ownership

`Service` owns application authority and SQLite metadata; `files` owns bounded
copying; `migration` owns archive validation; `Codex` owns isolated stdio transport;
`Bridge` routes tagged requests/events; React owns presentation only. No HTTP
server is started by the desktop application. Codex threads are ephemeral model
contexts; durable application sessions keep the recoverable visible conversation.

The `resources/policy.md` file defines host boundaries. The three adapted skill
copies only define their own workflows. `engineering-source.json` records upstream
provenance; no character-system installation is required. The generator child is
a fixed packaged entry point, and all its corpus inputs/templates/output are
redirected into that task's staging directory before execution.
