---
name: ai-workbench-maintainer
description: Maintain ai-workbench native muti-ai controls, simulated tests and portable projections. Use for changes inside this package.
---

# ai-workbench maintainer

Role: package development maintainer. Modes: read-only diagnosis or source patch
under applicable host task rules (Workspace requires an active task). Standalone
development uses README commands without Workspace tooling. Scope: package code,
tests and portable docs;
approved staging previews. Development status does not confer platform exposure.

Read [the maintenance contract](../../shared/maintenance.md). For code and Qt
validation load [development](references/development.md). For export changes
load [projection](references/projection.md). For tool selection and authority
load [MCP guidance](../../docs/mcp.md).

Preserve the lifecycle interface and independent tool states; accept completion
only through the adapter seam. Real services, accounts, credentials, dependency
installation, deletion and remote publishing require their own host authority.
For project terminal actions load [the dispatch contract](../../docs/project-terminals.md).
Keep dispatch observations separate from service state and model readiness.

Finish with relevant tests, native review for GUI changes and independent preview
checks for projection changes. Report simulated results and unverified real
integration separately; write reusable lessons into the owning contract.
