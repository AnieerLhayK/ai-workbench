# e-Chatter v0.1.0 acceptance record

Checked on Windows 11 x64 with Python 3.13.9, PySide6/Qt 6.9.2,
Codex CLI 0.163.0, Node 25.2.1 and PyInstaller 6.22.3. Node and the build
interpreter are development dependencies; the delivered application uses its
bundled runtime. Verification separates synthetic tests from real model use.

## Application and browser

The exported portable source passed 233 tests, with one explicitly skipped native
desktop test. The final application-domain checks passed 33 tests. Frontend
TypeScript/production build passed; three Vitest tests passed. Seventeen publisher
policy checks passed. Manifest/protocol validation reported zero errors; existing
manifest warnings remained unchanged.

Playwright Chromium was used after the in-app browser reported unavailable.
Checked light/dark themes, nested folders and search, character-switch warning
and cancellation, engineering confirmation, streaming cancellation, Doctor,
Maintainer, review and acceptance, settings and character registry. Compared
actual screenshots to the six accepted references with image inspection at
1536 × 1024 and checked the 900 × 640 minimum desktop layout. Local system fonts
and functional demo/version labels account for the documented design differences.

The native Qt WebChannel check passed separately in a fresh desktop process:
the rendered Doctor button saved diagnosis and handoff records, and cancelling
the rendered Generator confirmation created no Generator task. Native visual
inspection confirmed the embedded interface renders in the Windows desktop host.
The offscreen QWidget/PDF test process is not used for this WebEngine check.

## Boundaries and real Codex

Regression tests cover immutable originals, staging-only proposals, failed saves,
version conflicts, stale completions, task/session attribution, retained materials
across restart, denied task reentry, skill-path confirmation, explicit provisional
diagnosis, source README redirection and migration without credentials/staging.

Real Codex managed authentication was already available. The app-server adapter
verified effective disabled execution features/MCP entries, listed eight available
models, generated a synthetic character reply and saved a real Doctor diagnosis
linked to character version 1. No credentials were read into application records
or copied. Interactive first-time account registration/login was not automated.

## Distribution limits

The Windows directory/ZIP includes Python, QtWebEngine, built frontend, adapted
engineering resources and license notices. The build checks frozen application
module code against the final source before creating the ZIP. It excludes Codex,
personal characters, application libraries, credentials and Workspace runtime.

A clean Windows VM with Python/Node entirely uninstalled was not available.
Restricted-environment frozen checks are recorded with the external release
evidence; they complement, and do not replace, that fresh-machine acceptance.
This release is suitable for local trial; a wider release should repeat the
clean-machine and first-time official-login checks.

The two independent review axes found and resolved Doctor reentry, material
recovery after restart and the language-specific document-edit gate. A follow-up
review also corrected provisional sample text being parsed as skill invocation.

## Security follow-up (2026-10-18)

The two original boundary checks failed before the patch: diary generation
inherited user tool configuration, and an oversized DOCX reached full expansion.
The shared generation-only policy now serves all three model adapters without
changing the history/approved-experiment transport. Unsupported exec isolation
stops before evidence submission; app-server rejects ineffective MCP readback.

Post-patch checks passed 287 tests including publisher-policy checks, with the
ordinary suite's one native test skipped; the native WebChannel test passed
separately. Thirty-seven focused checks cover the isolation policy, tool events,
MCP merging, unsupported clients and DOCX boundaries. The independent bypass
review found internal XML entity expansion; UTF-8/UTF-16 regression checks failed
before the DTD rejection and passed afterward. Normal UTF-16 and exactly-16-MB
XML remain supported. Rejected attachments preserve source bytes and state.

All three actual adapters generated successfully using synthetic input and
existing Codex authentication. e-Chatter also saved a diagnosis tied to the
synthetic role response. These checks establish compatibility with the tested
CLI, not every Codex version or every future integration. No connected-service
write, real corpus or credential export was used.
