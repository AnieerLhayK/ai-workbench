# Personal Experiment Box

Independent native Qt entry: `python -B scripts/launch_experiment_box.py --config
<external-config.json>`. Explicit `--demo` stays memory-only: no accounts, real
materials, terminals or Runner. Normal first use is empty. The desktop shortcut
reactivates the existing window for the same resolved data root.

## Workflow

1. Create a card through the installation-bound CLI, overview assistant or manual form.
2. Read goals, next actions, history and proposals. Routine updates save immediately.
   Goal changes, completion, bulk changes and script plans require human review.
3. Inspect exact differences or the goal, changed files, full command, read/write
   roots and timeout. Confirm changes or approve one offline round. Cancel leaves
   the proposal pending; Return for revision cancels it without applying changes.
4. Reopen to continue the conversation and inspect actual output. Neither terminal
   dispatch nor a zero exit code establishes completion of the trial's goal.

Window: 1440×1000, minimum 1000×700; sidebar, scrollable reading/decision area and
assistant pane. Narrow windows expose an assistant drawer. `@` opens five templates;
Ctrl+Enter sends, Escape hides the menu, arrows/Enter select. Attachments belong to
one request. Drafts survive trial switches and external updates. Failed saves keep
manual forms open; cancelling forms writes nothing.

## Modules and authority

- **ExperimentService** is the shared UI/CLI/assistant business interface. Untrusted
  JSON submits/reads proposals only. Saving a manual form is an explicit human edit;
  the native review component alone calls `decide` for critical proposals.
- **TrialStore.transaction** owns cross-process locks, reload, v1 backup/migration,
  revisions and atomic commits. `trials.json` contains authoritative requests,
  provenance and trial/overview conversations. Malformed files stop without overwrite;
  `trials.v1.backup.json` preserves old bytes. CAS conflicts keep drafts for review.
- **CodexAssistant** reuses e-Diary's subprocess/cancellation foundation and the
  existing Codex-managed login. Ephemeral generation uses JSON Schema, ignores user
  config/rules, disables tools/host skills/MCP/browser/hooks, and uses an app-owned
  catalog with shell disabled and apply-patch removed. It never copies credentials
  or reads main Codex history. The dedicated
  [instructions](../src/ai_workbench/experiment_box/assistant_policy.md) define role,
  scope, evidence and refusal. Every returned proposal still passes host policy.
  Closing cancels unfinished generation; no new model call runs after closure.
- **WindowsSandbox/Runner** uses `command/exec`, never unsandboxed `process/*`.
  Explicit native MXC (Codex CLI 0.163+ on a supported Windows build) uses
  restricted policies or equivalent named profiles to deny reads by default,
  allow only the trial and runtime, and disable network. Controlled read/write,
  network and child probes must pass before a user script runs. Unsupported native
  isolation stops without weaker/unrestricted fallback or automatic retry. Approval
  binds revisions, the complete proposal and existing file hashes, once only.
- **ExperimentLauncher** retains the separate confirmed manual terminal Interface.
  The human reviews the resolved external directory and full PowerShell command
  before immutable dispatch. CLI/assistant cannot invoke it. Existing fixed
  Codex/Claude launchers remain compatible. Terminals and approved detached scripts
  survive GUI closure. Runner output/exit/interruption has distinct provenance;
  human/CLI/assistant results remain observations. Execution never marks completed.

Private files are not tamper-resistant against their same-user owner. Do not claim
that the CLI prevents direct JSON edits or importing Python internals. The app API
enforces business capabilities; native sandbox isolation confines approved scripts.

## Installation and updates

Reuse Python 3.13+/PySide6 6.9.2 and existing Codex/shell runtimes. The installer adds
no dependencies or global PATH, account or main Codex configuration changes.

```powershell
./scripts/Install-ExperimentBox.ps1 -DataRoot <app-data> -DesktopRoot <desktop> `
  -Pythonw <pythonw.exe> -Python <python.exe> -Terminal <wt.exe> `
  -PowerShell <powershell.exe> -CodexCli <existing-codex-launcher>
```

After inspecting owned config/shortcut, use `-Upgrade`. Ownership checks precede
replacement; config, shortcut and owned CLI launchers are backed up and unknown
config fields preserved. `-RunnerDisabledReason <reason>` records a known local
limitation and disables Run. Clearing it never bypasses real Runner checks.

App data owns config, JSON, backups, locks, private generation materials and
per-trial workspaces. Exclude these from source/exports. The private
`experiment-box-cli.cmd` is bound to this installation; see
[CLI and assistant guide](experiment-box-cli.md). Optional `codex_cli`, `python`,
`powershell` and `model` identify existing trusted runtimes. Missing assistant/Runner
settings do not prevent manual cards. Automatic roots derive from trial IDs and
never use old manual directory/command fields.

## Acceptance and maintenance

Run source and independent-export pytest/QtTest with staging temp paths. Cover
concurrent writers, CAS/idempotency, migration/corruption/failed saves, stale or
duplicate approvals, cancellation, provenance forgery, bounded attachments and
injection, path/reparse escapes, draft/selection preservation and fixed terminal
plus e-Diary compatibility. Review actual native screenshots against the three
approved concepts, normal/minimum sizes, overview selection, typography, colors,
spacing, keyboard focus, scrolling and the assistant drawer. Browser tests do not apply.

Record real generation and sandbox evidence separately from controlled Adapters.
If native restrictions fail, record blocked acceptance; never claim an actual round
succeeded. Do not start Commander/Hermes or invoke Pi as fixtures.

Maintenance lesson: accepting a permission profile syntactically does not prove
the installed Windows backend enforces restricted reads. Validate capabilities
and actual isolation before enabling execution, with no fallback.
