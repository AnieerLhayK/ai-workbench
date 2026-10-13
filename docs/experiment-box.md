# Personal Experiment Box

A separate native Qt application for manual trials. Open the installed desktop
shortcut or run `python -B scripts/launch_experiment_box.py --config <external-config>`.
Use `--demo` for three memory-only example cards; demo never opens real terminals.
Normal first use is empty and never imports demo cards.

## Workflow

1. Create a trial with a name, goal, tags and next action. Optional source links
   accept HTTP(S). Status is manually selected: pending, in progress, paused or completed.
2. Add an absolute working directory and PowerShell command through Edit.
   Click Start trial, inspect the resolved directory and full command, then confirm.
   Cancel executes nothing. A new visible Windows Terminal opens for execution.
3. Record the result, referenced file paths and next action. File references are
   not copied. Dispatch does not change trial status or establish success.
4. Close and reopen to continue. Search matches names and tags; status filters
   do not alter the persisted selection.

## Modules and maintenance

TrialStore owns validation, snapshots and atomic persistence through save, select,
record, trials and snapshot. In-memory state changes only after a successful write.
Malformed existing data stops startup and stays untouched. Failed forms remain
open with drafts. Results append timestamps; no deletion, import, export or
automatic recovery is provided.

ExperimentLauncher owns launch/observe at the terminal Adapter Seam. Confirmation
produces an immutable CommandRequest. Windows uses the internal Terminal argv
builder and asynchronous broker; fixed Codex/Claude launchers retain their Interface.
User commands deliberately execute as PowerShell code. Names, directories and
Terminal argument syntax stay separate through literal quoting and encoding.
No command is installed, generated or run on startup.

Pending requests reject reentry. A ten-second timeout asks the user to inspect
opened windows; it neither terminates nor retries a process. Terminals and brokers
survive GUI closure. The application does not capture logs, stop trials, provision
accounts or invoke Pi. Demo and controlled Adapters verify behavior without execution.

## Local deployment

Reuse the host-approved Python/Qt runtime. Generate the owned icon with
`python -B scripts/make_icon.py --name experiment-box`. Run
`scripts/Install-ExperimentBox.ps1` with explicit `-DataRoot`, `-DesktopRoot`,
`-Pythonw`, `-Terminal` and `-PowerShell` paths. Existing configurations or shortcuts
are refused. Deployment and real dispatch require approved host integration
authority; ordinary development does not grant it.

External configuration contains `data_root`, `pythonw`, `terminal` and `powershell`.
The data directory owns `config.json`, `trials.json` and the window lock. Missing
terminal configuration affects launch only; recording remains usable. Keep account
secrets out of commands and notes. Local trial data and credentials are never exported.
The single-instance key includes resolved data root and application identity;
reopening activates the same window, independently of muti-ai.

## Completion evidence

Run `python -m pytest tests -q` using staging-backed temporary files. Cover data
round trips, malformed data, failed writes, command quoting, cancellation,
reentry/timeouts, keyboard interaction and fixed launcher regression. Review native
screenshots at normal/minimum sizes against the accepted concept; check an
independent export. Real acceptance uses a harmless command, checks terminal
survival after GUI closure, records a result and reopens the same data. Distinguish
native/real evidence from demo. Do not start an existing Commander as a fixture.
