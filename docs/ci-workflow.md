# CI workflow

muti-ai owns a separate native **CI 修复** panel. It shares no lifecycle with
Commander/Hermes controls or project terminals. The first version detects
GitHub.com Actions failures and starts a bounded local repair only after a
user click. It produces patches for review; push, PR creation and merge remain
outside this workflow.

## Use

1. Open **CI 修复** beside the project selector. Enter `owner/repository`, its
   existing local Git root, and the exact test command, such as
   `python -B -m unittest discover -s tests -v`.
2. Select `dsh`, `claude` or `codex`. Leave model empty to use that harness's
   existing default. Each agent retains its own model field. Existing native
   login remains with the provider; this panel never asks for an API key.
3. Under **更多执行设置**, set the installed `gh-fix-ci` directory if it is not under the current
   Codex skill root. The original skill is not bundled into this MIT package;
   its Apache license and assets accompany each private runtime copy.
4. Choose **开启监测** or **立即扫描**. Monitoring scans up to 100 open PRs per
   configured repository every 120 seconds. Non-Actions providers and Actions
   URLs belonging to another repository, including fork-owned runs, are ignored.
   Discovery is deduplicated by repository, PR number and exact head SHA.
5. Select a detected item and choose **开始修复所选项**. Review **查看补丁** and
   the job's test result. Demo never queries GitHub, launches a model or reads
   real projects.

The panel configures one repository at a time. The controller supports at most
20 repositories and 30–3600-second polling; an advanced client can submit these
settings through `CIClient.send("configure", values=...)`. The first panel does
not provide multi-repository editing. Switching the configured repository
retains prior job evidence. Old heads become superseded, never silently repaired.

## Runtime and authority

State is private under `<muti-ai data_root>/ci`. The UI submits ordered request
files; a process-held lock admits one detached worker as the state writer.
Settings are merged, saved atomically and snapshotted per repair. Closing a
window stops its observers, not the worker. **暂停监测** stops future automatic
queries; an already running repair finishes. There is no automatic repair retry.
Restarted workers mark unfinished jobs interrupted rather than claiming success.
Malformed state is retained without overwrite. A stale heartbeat is unconfirmed,
not proof that a process stopped. Runtime requests and receipts are private
operational state, not a new Workspace audit system.

Each repair makes a new detached clone without hard links, disables checkout
hooks and symlink creation, fetches only the requested PR ref, and verifies the
head again. The source branch is not edited. Agent/model/command/test settings
are immutable for that request. A push URL in the clone is disabled. Tests and
control-file changes require human review; they cannot earn `patch_ready` by
weakening their own assertions. A passing agent message or exit code alone is
insufficient: a real diff and independently executed configured tests are required.

Native completion has a ten-minute deadline; independent tests have five minutes.
On Windows, owned timeout process trees are stopped. Failures have safe categories,
not raw provider/account output. Patches and test output remain in private job
directories. No provider reasoning transcript is part of the application receipt.

## Native execution

DSH uses the official Desktop executable's installed SDK profile, with a fresh
home, native file/shell tools and only the selected CI skill. This is a separate
tool-capable Adapter; e-Chatter's generation-only profile is not used. Its current
validated version is `0.2.1-rc.2`. Existing provider/model selection is read from
the native Desktop profile, and an explicit model replaces only that selection.
Unsupported runtime versions stop with a compatibility error.

The Windows DSH sandbox needs the current caller to have `WRITE_OWNER` when it
applies its Low integrity label. Preparation adds only `TakeOwnership` for the
current owner on newly created private clone/temp directories, preserving an
original DACL snapshot. It checks ownership and rejects reparse roots. It does
not change the source repository, tool installation or global ACL template.
The Windows PowerShell preparation child receives its own system module path;
the parent/global environment is unchanged. Native ACL setup also creates its
own capability entries/labels inside these disposable directories.

Codex uses `codex exec`, workspace-write and the supported Windows `unelevated`
implementation by default. `codex_windows_sandbox` can explicitly select another
installed implementation. It does not switch to full access. MCP entries from
the current user config are disabled for this coding task. Codex and Claude start
in a controlled runtime directory, with the clone as an added write directory,
so PR-local runtime settings are not their launch configuration.

Claude Code uses its native print/stream interface and a process-local tool hook.
DSH uses a monotonic guard; both admit scoped file edits, read-only Git/GitHub
commands, and the configured test argv. Credential-display commands, remote
writes, instruction/Git metadata edits, path escapes and permission escalation
are denied. Skill calls must return successful loading receipts. Codex loading
is checked against a successful instruction read. Discovery alone is insufficient.

Independent verification uses the chosen DSH or Codex native sandbox without a
model call. Claude/custom runners default to the installed DSH verifier; advanced
settings may choose `verification_agent="codex"`. A missing verifier blocks test
acceptance. There is no unsandboxed verification fallback. Windows DSH reports
partial enforcement; these tests do not establish hostile-code or network
isolation. Only explicit, owner-selected repositories should be admitted.

## Custom runners and limits

Use another agent id plus a JSON command argv in the panel. Template values are
`{workspace}`, `{prompt_file}` and `{model}`; no shell interpolation occurs.
The command must emit JSONL with explicit `completed: true` and `skill_loaded:
true` receipts. These are that custom Adapter's contract, not proof of a native
vendor identity. The controller still requires a real patch and independent
tests. An unconfigured id fails; it never silently selects another agent/model.
Custom commands run with the user's authority and must honor the no-push,
no-PR and no-merge contract; the application does not enforce their behavior.

Actual model defaults belong to native configuration. DSH/Claude return emitted
model identities when available; Codex may report only the requested value.
Do not label a requested/default value as an observed model identity.

Native acceptance covered a synthetic Python failure, native skill
loading, real edits and tests. It does not prove arbitrary CI repair reliability.
Real remote monitoring, a chosen production repository, background startup at
login, cancellation UI and merge policy are not yet accepted. No automatic merge
or scheduled OS startup is installed by this implementation.
