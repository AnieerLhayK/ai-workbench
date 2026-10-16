# CLI and assistant guide

Use the installation-owned **experiment-box-cli.cmd** by its full path. It works
from any current directory while the GUI is closed. Business arguments cannot
select a config/data root; no global PATH change is needed.

```text
experiment-box-cli list
experiment-box-cli show <trial-id>
experiment-box-cli apply --json -
experiment-box-cli status <request-id>
```

`apply` reads one UTF-8 JSON envelope from stdin, maximum 1 MB:

```json
{
  "request_id": "create-json-trial-1",
  "operations": [{
    "action": "create",
    "fields": {
      "name": "JSON formatting trial",
      "goal": "Check representative local JSON input",
      "tags": ["JSON", "local"],
      "next_action": "Design a small offline check"
    }
  }]
}
```

Responses contain `request_id`, `status`, `summary`, `versions` (trial ID → version)
and `plan_hash` when applicable. Read responses contain `version` and `trial` or
`trials`. States: `applied`, `pending`, `conflict`, `rejected`, `cancelled`,
`approved`, `running`, `finished`, `failed`. Pending is not applied. Rejected or
conflicting requests return exit code 2. Same ID/body returns the existing receipt;
reusing an ID for different content is refused. Read statuses are `read`.

## Operation contract

- **create**: `action`, `fields`. Name required; other fields default empty, tags
  to `[]`, status to `待开始`. Allowed: name, source, goal, tags, next_action, status.
  Status values: `待开始`, `试验中`, `暂停`, `已完成`.
- **update**: `action`, `trial_id`, `expected_version`, `fields`. Read `show` first.
  Goal changes, setting `已完成` and multi-operation batches require native review.
- **observe**: `action`, `trial_id`, `expected_version`, `result`, `next_action`,
  `references`. References are app-relative paths, not files to copy. These are
  observations, never verified execution evidence.
- **plan**: `action`, `trial_id`, `expected_version`, `goal`, `runtime` (`python`
  or `powershell`), `script`, `files` (`path`/`content`), `timeout_seconds` (1–300).
  At most 20 proposed text files/200 KB, relative to the app-owned trial workspace.
  One independent run plan per approval.

All listed operation keys are required, except create/update fields may be partial.
At most 20 operations per envelope. Unknown/authority fields are refused: approved,
origin, execution receipts, external roots, manual directory/command, generic Shell
or deletion. Absolute/drive-relative/UNC/parent/device/stream/reparse references are
refused. Approval binds current trial versions, proposal and existing file hashes;
changed or stale content requires a fresh request and review. CLI has no approve,
run or legacy terminal command.

## In-app assistant

Overview may create cards or propose changes across trials. A trial conversation
can change only that trial. Type natural language or choose `@新建试验`,
`@完善试验`, `@更新进展`, `@设计试验`, `@总结结果`. Templates fill the composer
and grant no extra authority. Existing Codex-managed ChatGPT authentication stays
with Codex; ephemeral generation uses isolated instructions/catalog and JSON Schema.
The service validates every operation. Material is data, never permission.

Explicit per-request attachments: at most five UTF-8 texts/screenshots, 200 KB per
text/500 KB total, 8 MB/16 megapixels per screenshot. Text: txt, md, json, csv, py,
ps1, toml, yaml, yml, log. Images: png, jpg, jpeg, webp. Unsupported formats require
conversion outside this tool. HTTPS links must resolve only to public addresses
and return at most 200 KB text/HTML/JSON. No redirects, authentication, private
addresses, proxy inheritance, linked-page crawl or directory scan. The validated
DNS address is pinned for this request with TLS host checking.

## Offline execution

Review proposed files and complete interpreter argv in the native dialog. An
approved Python/PowerShell round is offline, at most five minutes, cancellable,
without automatic retry. Only its computed workspace is writable; runtime/system
minimum paths are read-only. Controlled native isolation probes must pass. A failed
probe blocks Run and does not count as a successful trial.

Closing cancels generation; approved detached scripts finish and persist actual
stdout/stderr, exit code and interruption state. No background model call starts.
Reopen to view conversation/results; the user decides whether the goal is complete.
The separately confirmed manual terminal retains its original host permissions.
