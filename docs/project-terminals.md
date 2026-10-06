# Project terminal launchers

Choose a directory explicitly on first use. The shared selector persists
`selected_project` and up to ten deduplicated `recent_projects` with theme and
expansion preferences in external data. Missing saved directories stay visible
and disable launch; never substitute another directory. A request captures the
directory before asynchronous dispatch. Selecting another directory affects
only later requests.

Claude and Codex each offer new/resume-latest actions. They use `claude`,
`claude --continue`, `codex`, or `codex resume --last` in the project directory.
No cross-project history option, task prompt, model override or permission
bypass is added. The CLI handles missing history, trust, login and agent status.

Optional external config keys: `terminal`, `powershell`, `codex_cli`, `claude_cli`.
Use absolute existing Windows Terminal/PowerShell paths and CLI `.cmd` or
executable paths. Missing values fail only the relevant action; service-only
configurations remain valid. Installer parameters are `-Terminal`, `-PowerShell`,
`-CodexCli` and `-ClaudeCli`; existing deployments merge these keys into their
external config instead of rerunning the refusing installer.

The TerminalLauncher Module's Interface is launch(tool, project, mode) and
observe(callback). Each tool rejects requests while pending, publishes a safe
error or successful handoff, then accepts deliberate additional windows. The
Windows Adapter builds a new-window Windows Terminal argument list and a
UTF-16 encoded PowerShell command with literal-quoted paths and fixed arguments.
Escape semicolons in every Terminal argument as well: its own parser splits
arguments before Windows shell processing, even when argv quoting is correct.
PowerShell stays visible after CLI exit. Its existing environment and provider
configuration are inherited; no global configuration is repaired.

A detached broker is polled without blocking Qt. Zero exit means terminal
handoff; nonzero exit reports failure. After ten seconds without a result,
report an unconfirmed dispatch and instruct the user to check opened windows
before retrying. Do not terminate that broker or any agent process on timeout
or GUI close. There is no session tracking or automatic retry.

Demo and controlled test Adapters satisfy the same Seam without real terminals,
accounts or network. Test command construction and dispatch through this
Interface; real evidence additionally checks terminal directory, CLI output and
GUI-independent lifetime. Working broker dispatch never proves model readiness.
