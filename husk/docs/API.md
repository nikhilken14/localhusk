# API reference (v1.0)

Base URL `http://127.0.0.1:8000/api/v1`. JSON everywhere; timestamps are ISO-8601 UTC (`...Z`).
Interactive docs: `/docs`.

## Conventions

* **Errors:** `{"detail": "<message>", "code": "<machine_code>", "request_id": "..."}` (validation errors: `detail` is a list).
  Every response carries `X-Request-ID`; the same id appears in `GET /logs`.
* **Pagination envelope** (conversations, messages, history, mail messages, logs, run/job-run history):
  `{"items": [...], "total": n, "limit": n, "offset": n}` with `?limit=` (1-200, default 50) and `?offset=`.
  Other lists (tasks, notes, agents, jobs, models, tools, calendar events) return plain arrays.
* **PATCH** ignores omitted fields; an explicit `null` is rejected for required fields (and clears nullable ones such as `due_at`).
* **Secrets** are write-only: `api_key` is accepted on `/llm/models` and never returned (`has_api_key` instead).

## Chat

| Endpoint | Notes |
|---|---|
| `GET /conversations?q=&archived=&pinned=` | `q` searches titles **and** message text. Pinned first, then newest. Items: `id,title,pinned,archived,provider_id,message_count,preview,created_at,updated_at`. |
| `POST /conversations` `{title?, provider_id?}` | |
| `GET /conversations/{id}` | Metadata only - messages come from `/messages`. |
| `PATCH /conversations/{id}` `{title?, pinned?, archived?, provider_id?}` | Rename / metadata. |
| `DELETE /conversations/{id}` | Deletes messages too. |
| `GET /conversations/{id}/messages?order=asc\|desc` | Paginated. |
| `POST /conversations/{id}/messages` `{content, provider_id?, temperature?, max_output_tokens?}` | Returns `{user_message, assistant_message, usage:{input_tokens,output_tokens,estimated}}`. Model = explicit > conversation's > workspace default. First message auto-titles a "New chat". |
| `POST /conversations/{id}/stream` | Server-sent events, one JSON per `data:` line: `{"type":"start","user_message":{}}` → `{"type":"delta","delta":"..."}`* → `{"type":"usage",...}` → `{"type":"done","done":true,"message":{}}`; failures end with `{"type":"error","error":"..."}`. If the client disconnects, the partial answer is saved with `status:"partial"`. |
| `GET /history?q=&since=&until=&days=&all=&role=` | Read-only. Default window = last 5 days (`all=true` to disable). Items add `matches:[{message_id,role,snippet,created_at}]` when `q` is set. |
| `POST /history/prune?days=` *(extra)* | The only call that deletes old chats. |

## Tasks / Notes / Calendar

* `GET /tasks?status=&due_before=&due_after=&overdue=&q=` · `POST` `{task, status?, due_at?, position?}` · `GET|PATCH|DELETE /tasks/{id}` ·
  `PATCH /tasks/{id}/status` `{status, position?}`. A task is a single line of text (`task`). Moving a task appends it to the target
  column (or inserts at `position`) and keeps positions in every column contiguous (0..n-1); delete compacts too. `completed_at` is set/cleared with `done`.
* `GET /notes?q=&color=&pinned=` (pinned → red → yellow → green → newest) · `POST` `{title, content, color, pinned}` · `GET /notes/{id}` · `PUT` (replace) · `PATCH` *(extra, partial)* · `DELETE`.
  `color` (`red|yellow|green`, default `yellow`) is the importance marker.
* **Calendar is local-only.** `GET /calendar/events?start=&end=&calendar_id=&q=` returns local events **overlapping** `[start,end)`.
  Events have `calendar_id, all_day, source ("local"), read_only`. Only local events can be edited or deleted.
* `GET /calendar/calendars` returns the local workspace calendar only · `PATCH /calendar/calendars/{id}` *(name/colour/enabled)* ·
  `POST /calendar/sync` is a no-op that ensures the local calendar exists (`message` explains local-only mode). Provider calendar sync is disabled.

## Mail

1. `POST /mail/accounts/oauth/start` `{provider:"google"|"microsoft", include_calendar:true}` → `{authorization_url, state}`. Open the URL in a popup.
2. The provider redirects to `GET /mail/accounts/oauth/callback`, which shows a page that calls
   `window.opener.postMessage({type:"husk-oauth", ok, account_id, message}, FRONTEND_URL)`; then refresh `GET /mail/accounts`.
3. `POST /mail/sync` `{account_id?}` pulls inbox + sent. `GET /mail/messages?account_id=&folder=inbox|sent|drafts|trash|spam|all&q=&unread=&has_attachments=`
   serves the local cache (paginated). `GET /mail/messages/{id}` fetches the body on first open. `PATCH /mail/messages/{id}` `{is_read}` updates the provider first.
4. `POST /mail/send` `{account_id,to[],cc[],bcc[],subject,body,html}` · `POST /mail/messages/{id}/send-reply` `{body,html,reply_all}` (202).
5. `DELETE /mail/accounts/{id}` → `{deleted, revoked}` (Google tokens are revoked; Microsoft has no revoke endpoint). Messages and mirrored calendars are removed.

Account `status`: `connected | needs_reauth | error`. A `409 reauth_required` means the user must reconnect.

## Agents

* `GET /agents` (each with `stats`: runs by status, `success_rate`, `last_run_at`, tokens) · `POST|PUT /agents` `{name, description, system_prompt, provider_id?, tools[], status}` ·
  `GET|DELETE /agents/{id}` · `PATCH /agents/{id}/status?status=active|paused`.
  `DELETE` disables linked automation jobs (and detaches them), cancels queued/awaiting runs, keeps run history: `{deleted, disabled_jobs, cancelled_runs}`.
* `GET /agents/catalog` → `{tools:[{id,name,kind,description,input_schema,requires_approval,available,server_id}], models:[...]}`. MCP tool ids look like `mcp:{server_id}:{tool}`.
* `POST /agents/{id}/run` `{input, plan?}` → 202 run. Without `plan`, the LLM plans (max 5 steps, only the agent's tools).
* `GET /agents/{id}/runs` (paginated) · `GET /agents/runs/{run_id}` (`status, plan, result, error, tokens, duration_ms, pending_approvals`) ·
  `POST /agents/runs/{run_id}/cancel` *(extra)*.
* `GET /agents/runs/{run_id}/events?after_sequence=0` → `{events:[{sequence,type,message,details}], next_sequence, run_status, done}`. Poll until `done`.
  Types: `run.queued, run.started, plan.created, step.started, step.completed, approval.required, approval.approved|rejected, run.completed|failed|cancelled, run.resumed`.
* `GET /agents/approvals?status=pending|approved|rejected|executed|all` · `POST /agents/approvals/{id}/resolve` `{decision:"approved"|"rejected", note?}` — approving re-queues the run, which then executes the step.
* `GET /agents/overview?since=&tz_offset_minutes=` → `{days:[{date,total,completed,failed,...}], totals, pending_approvals}`.
* Run status: `queued → running → awaiting_approval ⇄ queued/running → completed | failed | cancelled`.

## Automation

`GET|POST /automation/jobs` · `GET|PUT|DELETE /automation/jobs/{id}` · `PATCH .../enabled?enabled=true` · `POST .../run` (202; works when disabled) ·
`GET .../runs` · `GET /automation/summary` · `GET /automation/triggers`.
Job: `{name, description, trigger_type, trigger_config, agent_id?, input, enabled, skip_if_running}`. When `skip_if_running` is true, a job does not enqueue overlapping runs.

| trigger_type | trigger_config |
|---|---|
| `manual` | `{}` |
| `interval` | `{"interval_seconds": >=60}` |
| `cron` | `{"expression":"0 9 * * 1-5","timezone":"Asia/Kolkata"}` |
| `event` | `{"event":"task.status_changed","filters":{"to_status":"done"}}` — events/fields from `GET /automation/triggers` |

Events: `conversation.created, task.created, task.status_changed, note.created, note.updated, calendar.event_created, mail.message_received, agent.run_failed, approval.requested`.

## MCP / Tools

`GET /mcp/servers` (with discovered `tools`, `status`, `last_error`) · `POST /mcp/servers` (registers **and connects**; connection problems show in `status`, not as an HTTP error) ·
`DELETE /mcp/servers/{id}` · `PATCH .../enabled?enabled=` · `POST .../refresh`. `GET /tools?kind=&q=&available=` · `GET /tools/{id}` (permission details).

## LLM, usage, logs, health

* `GET|POST /llm/models` · `PUT|DELETE /llm/models/{id}` · `POST .../default` · `POST .../test` (always 200: `{ok, latency_ms, error}`) · `POST /llm/discover` `{kind, base_url?, api_key?, model_id?}`.
  Each model includes `connectivity:{status: connected|error|unknown, latency_ms, checked_at, error}`. Deleting the default promotes another model.
* `GET /usage/today?since=` → `{since, requests, input_tokens, output_tokens, total_tokens, default_model:{status,latency_ms,...}, models[]}` ·
  `GET /usage/summary?group_by=day|provider|model`. When a provider reports no usage, tokens are estimated and flagged `estimated`.
* `GET /logs?category=api|llm|agent|automation|mcp|mail|calendar|system&level=&q=&since=&until=` · `DELETE /logs`.
* `GET /health` · `GET /health/ready` (database, schema, secret store, workers; 503 if not ready).

## v0.9 → v1.0 route map (breaking)

| Old | New |
|---|---|
| `/chat/conversations[...]` | `/conversations[...]` (`GET /{id}` no longer embeds messages) |
| `POST .../messages` → assistant message | → `{user_message, assistant_message, usage}` |
| `/providers[...]` | `/llm/models[...]` (`PATCH` → `PUT`) |
| `/connections/mcp[...]` | `/mcp/servers[...]` (direct tool-call endpoints removed; tools run through agents) |
| `/agents/runs` (create/list) | `POST /agents/{id}/run`, `GET /agents/{id}/runs` |
| `/agents/approvals/{id}/decision` + `/execute` | `/agents/approvals/{id}/resolve` (execution is automatic) |
| `/agents/dashboard` | `/agents/overview` |
| `/agents/tools` | `/agents/catalog`, `/tools` |
| `PATCH /automation/jobs/{id}` | `PUT /automation/jobs/{id}` |
| `GET /history` deleted old chats | read-only; `POST /history/prune` deletes |
