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

## Multi-Agent desktop follow-up (2026-10-19)

The official DeepSeek account login completed in the dedicated application
credential store. Four independent status reads returned connected with both
advertised models. A real account-backed deepseek-flash request with reasoning
off returned the synthetic reply “连接测试通过。” with 37 stream updates and
matching actual model/effort metadata. No character corpus was submitted.
The earlier connection-ended notification did not reproduce in these checks;
its originating cause is not confirmed.

The official Harness runtime also passed three controlled local-endpoint tests:
streaming completion, cancellation and tool-event rejection. These tests use a
synthetic Key and do not establish real API Key service acceptance. Nine provider
checks, 33 existing application checks, three frontend checks and the native Qt
WebChannel check passed on the final desktop source candidate.

The previous desktop shortcut still targeted the old Codex-only portable build.
The multi-Agent bundle is built separately under agents-20261019; the shortcut
must be updated only after frozen-module/resource consistency and executable
startup checks pass. Existing data and the previous release remain in place.
Real API Key service acceptance and clean-machine acceptance remain outstanding.

Desktop delivery completed: the agents-20261019 portable build passed frozen
module checks, 47 web/resource hash comparisons, restricted-PATH demo startup
(exit 0), and ZIP integrity. The desktop shortcut now targets that build and
retains the canonical local data argument. Full package regression: 279 passed,
4 opt-in tests skipped; native WebChannel passed separately. Existing old
windows are not automatically replaced and must be closed before reopening.
This local trial delivery does not establish remote source publication.
