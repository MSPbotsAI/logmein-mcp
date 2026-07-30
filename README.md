# logmein-mcp

MCP server for **LogMeIn Rescue** (remote support/screen-sharing platform).
Exposes the Rescue API's session, chat log, note, and reporting methods as
MCP tools.

> Naming note: MSPbots' own integration is registered as "LogMeIn"
> (`subjectCode=LOGMEIN`); the vendor's current product name is "LogMeIn
> Rescue" (part of GoTo). This MCP covers exactly the 4 methods MSPbots
> itself has configured (Report, Session, Chat, Note) — see **API
> Reference** below for where the full method catalog lives.

## Overview

- Stateless HTTP service. No credentials are ever persisted — each request
  supplies its own username/password via headers, used only for the
  lifetime of that single request.
- Supports concurrent requests; per-request credential isolation is done via
  Python `contextvars`, not a global/shared client instance.
- Entry points: `POST /mcp` (MCP protocol) and `GET /health` (health check).
- Default port: `8080` (configurable via `MCP_HTTP_PORT`).

## Authentication

The Rescue API is a classic ASP.NET session-cookie API: `login.aspx`
authenticates with an email/username + password and returns an
`ASP.NET_SessionId` cookie, which every subsequent call relies on — there
is no bearer token or API key. To keep this server fully stateless (no
session cached across MCP calls), it performs a **fresh login on every
single tool invocation**, then makes the real API call(s) on that same
short-lived `httpx.AsyncClient` (and therefore the same cookie) before
discarding it entirely.

### HEADER 授权参数说明

| Header | 类型 | 是否必填 | 默认值 | 枚举值 | 字段描述 | Example |
|---|---|---|---|---|---|---|
| `X-LogMeIn-Username` | string | 是 | 无 | 无 | LogMeIn Rescue 账号邮箱/用户名 | `admin@example.com` |
| `X-LogMeIn-Password` | string | 是 | 无 | 无 | 对应密码 | `••••••••` |

Missing either header returns `401`:
```json
{
  "error": "Missing credentials",
  "message": "This server requires the X-LogMeIn-Username and X-LogMeIn-Password headers",
  "required_headers": ["X-LogMeIn-Username", "X-LogMeIn-Password"],
  "optional_headers": []
}
```

An invalid username/password surfaces as a tool-level error (`Error:
LogMeIn Rescue API error: login failed: INVALID`), not an HTTP-level
error, since the failure only becomes known after the login step inside
the tool call.

## Environment Variables

| Variable | 类型 | 是否必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `MCP_HTTP_PORT` | int | 否 | `8080` | HTTP 监听端口 |
| `MCP_HTTP_HOST` | string | 否 | `0.0.0.0` | HTTP 监听地址 |
| `LOGMEIN_BASE_URL` | string | 否 | `https://secure.logmeinrescue.com/API` | Rescue API 基础 URL |

## MCP Endpoint

- `POST /mcp` — MCP protocol (streamable HTTP transport)
- `GET /health` — health check, returns `{"status": "ok", "service": "logmein-mcp", "transport": "http"}`

## Tool List

| Tool | 功能 | 参数 |
|---|---|---|
| `logmein_get_report` | 生成并获取 Rescue 报表（依次调用 setReportArea + 可选 setReportDate_v2 + getReport_v2） | `report_area`（必填，0-10 枚举），`node`（可选，默认 `-2`），`nodetype`（可选，默认 `EXTERNALROOT`），`begin_date`/`end_date`（可选） |
| `logmein_get_session` | 列出某个节点（技术员/频道）当前/近期的会话 | `node`（必填），`noderef`（可选，`NODE`/`CHANNEL`，默认 `NODE`） |
| `logmein_get_chat` | 获取指定会话的聊天记录 | `session`（必填，会话 ID） |
| `logmein_get_note` | 获取指定会话的技术员备注 | `session`（必填，会话 ID） |

Responses are the vendor's raw pipe-delimited text (starting with `OK` or
`ERROR`, never JSON), returned as-is — consistent with how the Rescue API
itself replies.

## 测试示例

```bash
# Health check
curl -s http://localhost:8080/health

# Call a tool via the MCP protocol (streamable HTTP) — requires an
# initialize handshake first per the MCP spec; abbreviated example below
# shows the tool-call request body only:
curl -s -X POST http://localhost:8080/mcp \
  -H "X-LogMeIn-Username: admin@example.com" \
  -H "X-LogMeIn-Password: <your-password>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <session-id-from-initialize>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "logmein_get_session",
      "arguments": {"node": "57554", "noderef": "NODE"}
    }
  }'
```

**Live-verified** (2026-07-30) against a real Rescue account
(ThrottleNet, Inc): `logmein_get_session` (node = the account's own
AccountID) returned `OK` with the session table header (no active
sessions at test time — a valid empty result, not an error);
`logmein_get_report` with `report_area=2` (Login report) chained
`setReportArea` → `getReport_v2` and returned `OK` with the Login report's
column header; `logmein_get_chat` and `logmein_get_note` were called with
a non-existent session ID and correctly returned `ERROR` (the vendor's
documented response for an unknown session — not an auth failure,
confirming the login pipeline works). A separate handshake using a
deliberately wrong password correctly surfaced `Error: LogMeIn Rescue API
error: login failed: INVALID`.

## API Reference

- Overview (public, no login required): https://support.logmein.com/rescue/help/rescue-api-reference-guide-articles
- Method-specific pages used by this server:
  - Login: https://support.logmein.com/rescue/help/API_map_account_info
  - Session Management (getSession_v3): https://support.logmein.com/rescue/help/API_map_session_management
  - Reporting (getChat, getNote, getReport_v2, setReportArea,
    setReportDate_v2): https://support.logmein.com/rescue/help/API_map_reporting

## Known Gaps

- **Scope is exactly MSPbots' 4 configured endpoints (Report, Session,
  Chat, Note), not the vendor's full API surface** — the Rescue API also
  exposes Account Management, CRM integration, and ReportArea
  configuration methods (date/time/delimiter/output format setters) that
  MSPbots does not use; those are out of scope here.
- **The `authcode` field MSPbots also stores for this integration is not
  used by this server.** The Rescue API documents `authcode` as an
  alternative to logging in (mainly for the Session Management methods;
  Reporting methods require login regardless of `authcode`). Live testing
  showed that the provided `authcode` value was rejected
  (`INVALID_SECRETAUTHCODE`) when passed, while plain
  username+password login worked correctly and was sufficient for all 4
  endpoints — matching MSPbots' own stored config, which has no auth
  template defined beyond credentials. This server therefore relies
  solely on the login-cookie flow.
- **The vendor rate-limits `getReport_v2` to once per 60 seconds per
  account** (documented). Calling `logmein_get_report` more frequently
  than that will likely fail at the vendor side.
- **`node`/`nodetype` defaults for `logmein_get_report`** (`-2` /
  `EXTERNALROOT`, meaning "the whole External Technicians tree") were
  chosen to match a whole-account report, mirroring MSPbots' generic
  "Logmein Report" endpoint naming (MSPbots' own stored config has no
  specific node/nodetype recorded). Callers needing a report scoped to a
  single technician or group should override both parameters.
