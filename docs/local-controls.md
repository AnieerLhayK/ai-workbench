# Local controls

The window observes one Controller per tool. Each local Adapter communicates
with a detached, process-locked worker through atomic JSON in the configured
external data directory. Opening a window starts observers, not services.
Closing it leaves workers, service processes and pending requests intact.
Project terminal actions have a separate [dispatch contract](project-terminals.md)
and never enter the service process discovery or stop paths.

## Configuration and deployment

`scripts/Install-Local.ps1` takes explicit local data/desktop roots and existing
runtime paths. It writes a private `config.json` and one shortcut. It does not
install dependencies, edit service settings, or overwrite an existing deployment.
Generate the owned icon with `python -B scripts/make_icon.py` before deployment.

Configuration fields: `data_root`, `pythonw`, `npx`, `node`, `hermes_home`,
`hermes_pythonw`, `hermes_exe`. All are absolute local paths. Keep the configuration
outside source and exported previews. Theme and the `expanded_categories` ID list
are stored in `preferences.json`; updates merge and retain other fields. Missing
or malformed expansion lists default to ChatGPT/Hermes; an empty list collapses
all categories and unknown IDs are ignored. The portable Catalog Module owns
category order, titles and launcher membership, independently of host platforms.

Copy [the placeholder example](../examples/config.example.json) outside the clone
and replace every value before launching real mode. Existing Hermes/Node runtimes
are prerequisites. See [README](../README.md) for isolated dependency installation
and Commander browser authorization; the workbench does not provision accounts.

## Process and connection semantics

Workers match executable, module command, PID and creation time. Hermes uses
its configured profile PID/runtime records, including Windows interpreter
children. Ambiguous targets or failed probes disable that row until resolved.
Stopping rechecks identity. No blanket termination of Node/Python processes.

Commander uses `npx -y @wonderwhy-er/desktop-commander@latest remote`. A live
npx installer is not a ready device. The worker recognizes a small whitelist
of CLI readiness, disconnection, authorization and startup-failure events, and discards raw
output. A changed upstream message results in unconfirmed connection status.
Existing instances without captured output remain explicitly unconfirmed.

For Commander only, the launcher copies its inherited environment and defaults
`NODE_USE_ENV_PROXY` to `1` when a nonempty HTTP(S) proxy variable exists (upper
or lower case). Explicit settings, including `0`, remain authoritative; without
proxy variables it keeps direct networking. Nothing is written to global
environment settings and proxy URLs are never logged. This needs a Node runtime
with built-in environment-proxy support; local verification uses Node 25.2.1.
Older runtimes need separately approved runtime maintenance, not a TLS bypass.
See [Node's network guidance](https://nodejs.org/learn/http/enterprise-network-configuration).

Startup errors retain only a fixed failure category and numeric exit code.
Messages distinguish expired/invalid/denied device authorization, authorization
timeout, network failures and local runtime/install errors. Unknown errors remain
explicitly unknown. The worker waits asynchronously for the output reader before
completing a failed start. A three-second drain limit (within the startup deadline)
reports incomplete output explicitly. Reader generations prevent an old launch
from changing a retry. It never persists upstream error text, account identifiers,
tokens or codes.

Hermes uses its existing virtual environment and `HERMES_HOME`; readiness is
checked against its current profile runtime record. Stop uses `gateway stop`.
Connection problems do not stop the process. Auth remains with each provider;
this application does not read, export or reset credentials.

Startup waits at most 120 seconds, or 600 when browser authorization is requested;
stop verification waits 30 seconds. A timed-out launch is not retried automatically.
Only this operation's unready launcher can be cancelled. Remaining live processes
stay reflected in the switch. Failed stop keeps the actual running state.

## Maintenance

Keep the UI independent of process details. Demo and controlled test Adapters
exercise the same Controller. GUI tests use QtTest and native screenshots, not
browser checks. Changing local deployment needs explicit host target authority.
Personal legacy migration stays in the authoritative host; it is not exported.
