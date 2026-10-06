# Projection workflow

1. Review [the explicit contract](../../../projection-contract.json). Add only
   requested portable source, tests, launchers, docs or independently written
   skills. Source files and generated `PROJECTION_SOURCE.json` are separate lists.
   Public path additions require authorization. Do not export host registrations,
   runtime payloads or the personal legacy desktop migration script.
2. Select an empty approved staging directory outside the package. Run
   `python -B scripts/projection.py export --destination <directory>`.
   The generator refuses linked paths and nonempty destinations by default.
   To update an existing preview, use `export --refresh`: it checks the current
   preview and requires exactly the same file inventory before overwriting.
   It never deletes content. A changed inventory needs a new empty directory.
   Keep failed previews for diagnosis until authorized cleanup.
3. Run its checker, launcher and tests from the exported directory using the
   existing interpreter and an external test temp path. Capture evidence that
   neither host governance nor source import paths are required.
4. Review file inventory, document links, missing/private files and machine
   paths. Treat screenshots and test temp files as transients. The requested
   preview remains a staging handoff artifact until accepted or superseded.
5. Own public content is MIT; official updates use the authoritative Workspace's
   registered `ai_workbench` publisher through its aggregate synchronizer and
   active external-write task. Read the registry only in that host checkout.
   Independent clones can verify/develop without host commands. External PRs
   return to Workspace for review and regeneration. Never maintain the public
   checkout as a second source or copy private Workspace Git history.
6. Local previews may have a null source commit. Public payloads require a
   reviewed 40-character Workspace revision. The marker includes only package,
   relative source location and revision. Re-exporting a clone preserves its
   provenance unless explicitly supplied a new source revision. The checker
   skips root Git metadata without traversing it and checks every payload file.
   Run it before installation/testing creates local artifacts. An unrecognized
   nonempty remote stops for audit before generated contents are replaced.
7. Record source/remote revisions, tests and cleanup in the existing host receipt.
   Actual Pi applications must credit upstream, use and dependency licenses in
   their own docs and README when added. A preview grants no remote authority.
