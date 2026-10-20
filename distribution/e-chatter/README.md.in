# e-Chatter for Windows 11 x64

This is an independently buildable, managed e-Chatter snapshot. ai-workbench is
the development source; do not maintain a second development copy here.
SNAPSHOT.json records the source commit, payload hashes, dependency versions,
resource provenance, acceptance limits and the one Windows artifact identity.

## Download and use

Extract the complete Windows ZIP and open e-Chatter.exe. Python and Node are not
needed. Install your chosen Agent separately and connect in Settings. Use your
own Codex account, or DeepSeek Harness 0.2.1-rc.2 with official account/API Key.
Other Harness versions are refused until their isolation has been qualified.
Codex must support the restricted app-server configuration documented in
[the application guide](docs/e-chatter.md). Missing Agents do not prevent opening
the GUI; Settings explains connection failures.

The first launch has no characters. Import your own SKILL.md character folders.
Conversation and role data default to %LOCALAPPDATA%/ai-workbench/e-chatter;
--data selects an existing library. Updates replace program files only. Keep the
entire old program directory to roll back; rollback does not downgrade data.
Credentials and personal characters are never in this distribution.

## Independent source installation

Maintainers need Python 3.13+, Node 22+ and npm. Create an external virtual
environment and install this directory with `python -m pip install ".[dev]"`.
In frontend/e-chatter run `npm ci`, `npm test` and `npm run build`.
From this directory run:

```powershell
python -B -m pytest -q -p no:cacheprovider tests --basetemp <external-test-directory>
python -B scripts/launch_e_chatter.py --demo
python -B scripts/build_e_chatter.py --staging <external-build-directory> --output <external-release-directory>
```

The tests default to controlled providers. Opt into the native Qt test with
E_CHATTER_RUN_NATIVE=1; opt into the three synthetic local-endpoint official
Harness tests with E_CHATTER_RUN_DSH=1. They do not prove real account or Key
service acceptance. See docs/release-verification.md for the release gates.

## Stable promotion and artifact reuse

Only ai-workbench's `scripts/promote_e_chatter.py` can create new snapshots.
Preview an explicit committed source first, then run its execute mode. Each
version is immutable. Candidate and stable pointers are separate. Both product
channels reference one ZIP and SHA-256; never build separate packages and label
them as the same artifact. This snapshot does not publish or access a remote.
