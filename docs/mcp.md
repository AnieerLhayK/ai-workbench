# Tools and MCP boundaries

| Tool category | Use here | Authority boundary |
| --- | --- | --- |
| File/search/Git tools | Scoped source edits and delivery | Active host task and Git policy |
| Shell with existing Python | Tests, native controls, staging preview | Real processes require named tool/profile authority; no environment install |
| Native GUI observation | Window/layout/animation evidence | Only the workbench window; account verification stays with the user |
| Browser frontend tools | No current native Qt role | Browser test checks are not applicable |
| Desktop Commander MCP | Optional read-only connectivity evidence | Explicit device/account/service scope required; no credential reset |
| Hermes integrations | Configured local gateway lifecycle | Explicit profile/process and external data scope required |

The workbench adds **no MCP server** or credentials. Tool availability is not write
permission. Prefer the smallest tool sufficient for evidence; record failures
and actual limitations. Future connection configuration must reference approved
external credential storage rather than embedding secrets in source or previews.
