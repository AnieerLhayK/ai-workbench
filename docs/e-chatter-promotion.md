# e-Chatter candidate and stable promotion

ai-workbench remains the only development source. character-system receives
immutable, independent snapshots under applications/e-chatter/versions/. Fix
source here and promote a new version; never patch a generated snapshot.

Update the app VERSION, frontend package/lock versions and the independent
distribution/e-chatter/pyproject.toml together. Commit, validate and independently
review the development batch, then integrate locally into main before execute.
Source may be an earlier accepted commit only when every selected input still
matches it. No dirty or untracked selected inputs are allowed.

```powershell
python -B scripts/promote_e_chatter.py preview --source-revision <full-commit> --version 0.2.0-rc.1 --staging <external-staging> --output <external-release-root>
python -B scripts/promote_e_chatter.py execute --source-revision <full-commit> --version 0.2.0-rc.1 --staging <external-staging> --output <external-release-root> --build-python <build-environment-python>
```

The build interpreter needs Python 3.13+, PySide6 6.9.2, PyYAML, pytest,
setuptools and PyInstaller 6.22.3; Node/npm are build-only dependencies. The
explicit contract exports only the application, shared isolation, adapted
resources, frontend and independent tests. It uses Git blobs, not working files.
External staging hosts installation, browser-independent frontend tests, native
Qt tests, freeze checks and restricted-PATH demo startup. Failed runs remain for
diagnosis and never replace an active snapshot. Successful scratch can be
removed by its owning host after evidence has been retained.

Outputs are one versioned Windows directory/ZIP, SHA256SUMS and release.json.
The source SNAPSHOT.json lists payload hashes, resource origins, exact build
dependency versions and artifact identity. Both development receipts under
distribution/e-chatter/releases/ and character-system's candidate/stable pointer
reference that same artifact. This command neither pushes Git nor publishes.
Only declared source and generated frontend enter the snapshot; environments,
test staging, personal roles, credentials and corpora do not.

Release candidates update candidate.json only. An existing version is never
reused, including incomplete activation; retain the failure and use a new
candidate version after fixing the source. Previous version directories and
stable.json remain intact. Pointer replacement is the activation commit point.
The program never moves user libraries or rewrites data for a rollback.

Stable versions additionally require an external --acceptance JSON receipt for
the exact source_revision and version. Its checks must include codex_real,
deepseek_account_real, deepseek_key_real and clean_windows11, each with
passed=true and a nonempty evidence description. The maintainer is responsible
for real evidence; the receipt is not a cryptographic attestation. The snapshot
stores only passed/missing names. Full steps are in
[the standalone acceptance checklist](../distribution/e-chatter/release-verification.md).

The source snapshot is independently buildable; reproducibility of a fresh
binary is not a claim of byte-for-byte identical archives. Product release
synchronization always reuses the originally verified ZIP. Future remote
publication must explicitly add this application to its registered contract;
this local promotion does not change the remote projection boundary.

When committing a promoted snapshot, stage the exact SNAPSHOT.json file inventory
and its manifest, including force-adding the declared generated web assets if a
copied source ignore rule hides them. Verify every declared file against its Git
blob before integration. The character-system application attributes preserve
snapshot bytes across checkouts, including Windows metadata line endings; do
not normalize or format an immutable snapshot to satisfy a host formatter.
