# ai-workbench

Personal helper tools and results. Capabilities are limited and usefulness on
other machines is not guaranteed. Version 0.3 provides **muti-ai**, a native Qt
window with independent Commander/Hermes controls, project terminal launchers
for Codex and Claude Code, and an explicit demo.
Workspace remains the authoritative source.

This public repository uses independent projection history. Own content is
[MIT](LICENSE); dependencies retain their own licenses. Issues welcome feedback
without a promise of general support. External PRs return to Workspace for review
and regeneration by the registered publisher. No installer is provided yet.

The companion [Frame-for-AI-workspace](https://github.com/AnieerLhayK/Frame-for-AI-workspace)
shows the workspace organization and maintenance methods behind these tools,
and offers a starting point for your own agent-assisted workspace.

[中文说明](README.zh-CN.md)

## Use

The configured desktop entry is **muti-ai**. One scrollable window groups tools
under ChatGPT, Claude, Codex, Hermes and OpenCode, in that order. Expand ChatGPT
for Remote Desktop Commander, Hermes for Hermes Bot, or Claude/Codex for their
terminal actions. OpenCode shows
“暂无启动器” (no launcher). Several categories can stay open together.
ChatGPT and Hermes start expanded; later openings restore the last selection.
Collapsed headers still show live status and flag errors. Category headers
support Tab focus and Enter/Space activation; collapsing does not control services.
Opening reads current state; closing preserves services and pending operations.
Repeated opening brings back the existing window. The settings button selects
light or dark mode and remembers it; there is no theme keyboard shortcut.

Each service row shows stopped, starting, running, stopping, failure, or an unconfirmed
state. Pending requests disable only that row. Connection failure does not turn
off a live process. A live installer is not a ready Commander device.
Account authorization stays in the provider's browser flow.
Failed starts show a safe reason category and exit code. If device verification
expired, retry through a fresh browser page; an unknown failure is not labelled
as an authorization failure. No raw account output is stored.
Commander enables modern Node's environment-proxy support for its own child
when HTTP(S) proxy variables already exist; an explicit Node proxy setting is
preserved. Global environment and Hermes configuration are unchanged.

### Project terminals

Choose a folder above the categories; no project is selected on first use.
The shared selector remembers up to ten recent directories outside source.
Each Claude/Codex row offers **新建会话** (new) and **恢复最近会话** (resume latest).
Each deliberate click opens a new Windows Terminal window in the selected
project. Both buttons for that tool are disabled while dispatching; the other
tool remains available. Missing or moved directories require a new selection.

New commands are `codex` and `claude`; resume uses `codex resume --last` and
`claude --continue`, with project filtering retained. CLI history, login, model,
permissions and project instructions stay with each tool. The workbench sends
no task prompt and adds no permission bypass. A missing history is shown by the CLI.
“已打开终端” means successful terminal handoff, not agent readiness. CLI errors
and trust/login prompts remain visible in the terminal. Changing the selector
does not change submitted requests or existing sessions. Closing muti-ai leaves
terminals and dispatches intact. There is no terminal stop button or session list.

## Quick start: demo

Use Python 3.13+ and **PySide6 6.9.2**. In a dedicated environment managed under
your host's storage rules, install dependencies and run the explicit demo:

```powershell
python -m pip install '.[dev]'
python -B scripts/launch.py --demo
```

Demo requires no provider accounts and opens no real terminals or services. Real controls
require Windows, existing Node/npm and Hermes environments. Commander downloads
`@latest` through npx as needed; the workbench does not install Hermes.

Copy [the placeholder config](examples/config.example.json) outside the clone,
replace all placeholders with absolute local paths, and keep data and credentials
external. `pythonw` must have PySide6 available; Hermes paths identify its existing
runtime/profile. Optional `terminal`, `powershell`, `codex_cli` and `claude_cli`
fields identify existing Windows Terminal, PowerShell and CLI executables or
`.cmd` launchers. Omit unused optional fields; missing fields affect only the
corresponding terminal action. Old service-only configurations remain valid.
From this package directory:

```powershell
./scripts/Start-Workbench.ps1 -Config <external-config.json> -PythonExe python
./scripts/Start-Workbench.ps1 -Demo -PythonExe python
```

Other shells can use PYTHONPATH=src and `python -B -m ai_workbench --demo`.
Real mode requires an external configuration and existing service runtimes.
See [local controls](docs/local-controls.md) for deployment and process semantics.

For a hidden desktop entry, [Install-Local.ps1](scripts/Install-Local.ps1) takes
explicit data/desktop directories and runtime paths. It refuses existing targets
and installs no dependencies. Keep the clone at its deployed path: the shortcut
points to its source. Commander authorization follows the
[official browser flow](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/remote-device/README.md).
Enable/select Desktop Commander Remote in your chat client and authorize the same
device. Client availability and provider permissions are separate prerequisites.
Hermes authorization stays in its existing setup. Credentials are never read,
copied or reset by this workbench.

## Maintain and verify

Read [AGENTS.md](AGENTS.md), [maintenance](shared/maintenance.md), and the
[development workflow](skills/ai-workbench-maintainer/references/development.md).
Use pytest/QtTest with temporary files in the host-approved staging directory:

```powershell
python -B -m pytest -q -p no:cacheprovider --basetemp <approved-staging-tests> tests
```

GUI verification uses native windows, both themes, small window sizes and display
scaling. Browser checks are not applicable. Distinguish simulated tests, actual
process lifecycle evidence and end-to-end client connectivity.

## Portable preview

[The contract](projection-contract.json) and [export checker](scripts/projection.py)
export code, tests, owned assets and portable docs. Exclude private host records,
configuration, credentials, runtime logs and archives.

```powershell
python -B scripts/projection.py export --destination <empty-staging-directory>
python -B scripts/projection.py check --destination <preview-directory>
```

`PROJECTION_SOURCE.json` records only the package, relative source path and
Workspace commit. Local previews may have a null commit; public exports require
a reviewed Workspace revision. Check a fresh public clone before installation
or testing creates build artifacts:

```powershell
python -B scripts/projection.py check --destination . --require-revision
```

Windows CI uses Python 3.13, PySide6 6.9.2 and Qt offscreen for boundary checks
and simulated tests. It has no provider credentials and starts no real services.

An existing verified preview with identical inventory supports `export --refresh`.
Run its explicit demo and tests independently. Category registration lives in
the portable Catalog Module, without runtime host-platform discovery. OpenCode Web,
installable releases and Pi integration remain future work. Claude Remote Control
is not included. When Pi applications
are actually added, their docs and this README must credit the upstream repository,
explain the use and identify dependency licenses. No Pi application is included yet.
