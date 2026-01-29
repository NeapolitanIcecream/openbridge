## OpenBridge 设计方案：OpenAI Responses API → OpenRouter Chat Completions 兼容层

- **版本**：v0.1（draft）
- **日期**：2026-01-27
- **依据**：调研结论见 `docs/research.md`

### 1. 背景与目标

我们希望提供一个 **“OpenAI Responses API 外观”** 的 HTTP 服务（中间层），让只会调用 `POST /v1/responses` 的客户端（例如 Codex/agent 类应用）在不改动调用方式的前提下，改为走 **OpenRouter 的 Chat Completions API**（`POST /api/v1/chat/completions`）完成模型推理。

动机（来自调研）：

- OpenRouter 的 Responses API 仍为 beta 且明确 stateless，存在字段/语义对齐风险；而 Chat Completions 更成熟，工具调用与结构化输出能力更稳定。
- **两条路径都 stateless**：若要兼容 Responses 的 `previous_response_id`/会话能力，中间层必须实现“有状态”策略（或强制客户端每次传全量历史）。

### 2. 设计原则

- **不造轮子**：SSE 客户端解析、SSE 服务端输出、重试/熔断、配置管理、数据校验等尽量依赖成熟库。
- **主流与现代**：优先 FastAPI/HTTPX/Pydantic v2 等生态主流组件，避免小众框架与自研协议解析器。
- **兼容性分级**：明确“保证支持的最小子集”，对无法完美对齐的能力（如 `include` 高级扩展）做显式降级。
- **工具 = 协议**：对 OpenRouter（Chat Completions）侧统一使用 `type:"function"` 工具；对外再按 Responses 语义翻译（“工具虚拟化”）。

### 3. 支持范围与分级（对外承诺）

建议在 README/对外文档中以分级声明支持范围：

- **Level 0（最稳）**：`input` 为 string，纯文本输出，非流式，不使用 tools。
- **Level 1（推荐 MVP）**：支持 function/tool calling + tool loop（含流式 SSE 转写）。
- **Level 2（高级）**：支持 `previous_response_id`（需要中间层存储会话）+ structured outputs（JSON Schema）。
- **Level 3（协议化工具）**：支持“built-in/MCP/自定义工具”通过 function 虚拟化统一承载（例如 `apply_patch`/`shell` 等）；其他工具取决于客户端是否具备执行环境。

### 4. 总体架构

数据路径：

```text
Client (Responses API)
   |
   |  POST /v1/responses (stream? tools? previous_response_id?)
   v
OpenBridge (this project)
   |-- Request Normalizer / Validator (Pydantic)
   |-- Translator (Responses <-> ChatCompletions)
   |-- Streaming Bridge (SSE <-> SSE)
   |-- Optional State Store (previous_response_id)
   v
OpenRouter (Chat Completions API)
   v
Provider (e.g. OpenAI models via OpenRouter)
```

模块划分（建议的代码结构，非实现要求）：

```text
openbridge/
  api/                 # FastAPI 路由与响应封装
  models/              # Pydantic: Requests/Responses/Event schemas
  translate/           # 请求/响应/事件映射
  streaming/           # SSE 解析与 Responses 事件生成
  tools/               # 工具虚拟化注册表与映射
  state/               # previous_response_id 存储抽象与实现（memory/redis）
  config.py            # pydantic-settings 配置
  logging.py           # loguru/structlog 集成
```

### 5. API 设计（对外）

#### 5.1 必须实现

- `POST /v1/responses`
  - **兼容** OpenAI Responses Create 的请求体形状（至少覆盖调研中的“常用子集”）。
  - **支持** `stream:false/true` 两种模式：
    - 非流式：返回标准 response object（JSON）。
    - 流式：返回 `text/event-stream`，事件名遵循 OpenAI Responses streaming events。

#### 5.2 推荐实现（工程可用性）

- `GET /healthz`：健康检查（不依赖上游，或可选检查上游连通）。
- `GET /version`：返回版本、构建信息、运行时配置摘要（隐藏敏感信息）。
- `GET /metrics`（可选）：Prometheus 指标。

#### 5.3 按需实现（取决于客户端是否调用）

- `GET /v1/responses/{response_id}` / `DELETE /v1/responses/{response_id}`
  - 只有在启用“有状态存储”时才有意义；否则返回 404/501。

### 6. 核心映射设计（Responses → ChatCompletions）

本节将调研中的映射落成“可实现的规则”，并补齐边界条件。

#### 6.1 请求字段映射（常用子集）

| Responses 字段 | ChatCompletions 字段 | 规则 |
|---|---|---|
| `model` | `model` | 通过 **model 映射表**转换（例如 `gpt-4.1` → `openai/gpt-4.1`）；若未命中，按策略：透传或按前缀规则补齐。 |
| `instructions` | `messages` 的 `system`/`developer` | 转成最靠前的 system（或 developer）message。若启用 `previous_response_id`，**不得自动继承上一轮 instructions**（按 OpenAI 语义：每次都以当次为准）。 |
| `input`（string） | `messages=[{role:"user"}]` | 直接映射。 |
| `input`（items array） | `messages` | 用“归约算法”把 item 列表折叠成 chat messages（见 6.2）。 |
| `tools` | `tools` | 对内统一产出 `type:"function"` 的 tools（工具虚拟化），函数 schema 来自原始 tool 定义或工具注册表。 |
| `tool_choice` | `tool_choice` | `none/auto/required` 直接传；强制某函数按 OpenAI 兼容形状；`allowed_tools` 降级为“过滤 tools 列表 + tool_choice 用 mode”。 |
| `parallel_tool_calls` | `parallel_tool_calls` | 透传。 |
| `max_output_tokens` | `max_tokens` | 近似映射。 |
| `temperature/top_p` | 同名 | 透传。 |
| `verbosity` | `verbosity` | 尽量透传；必要时可在上游报错时进行“删除字段重试”的降级策略。 |
| `text.format`（json_schema） | `response_format` | 映射为 OpenRouter 的 `response_format: {type:"json_schema", json_schema:{name,strict,schema}}`（见 6.4）。 |
| `stream` | `stream` | 透传；但需要做 SSE 协议转写（见 7）。 |

对无法稳定对齐的字段建议：

- `include`：默认忽略（可在响应 `metadata` 中标注已忽略字段，便于排障）。
- 其他高级/实验字段：采取“白名单透传 + 失败降级（重试）”策略，避免引入不可控兼容性风险。

#### 6.2 `input` items → `messages` 归约算法（支持工具 loop）

目标：把 Responses `input` 的混合 items（普通消息、历史 output items、tool outputs）转换为 ChatCompletions `messages`，确保工具调用关联字段正确。

关键关联规则（调研结论）：

- Chat 的 `tool_calls[].id` / tool message 的 `tool_call_id` **对应** Responses 的 `call_id`。

推荐算法（逻辑描述）：

- **message-like items**（具备 `role` + `content`）：直接 append 为 chat message。
- `type:"function_call"`：转成 assistant message 的 `tool_calls`（content 置空）。
- `type:"function_call_output"`：转成 `role:"tool"` message，`tool_call_id=call_id`，`content=output`（若非 string 则 JSON 序列化）。
- `type:"*_call"` / `type:"*_call_output"`：当作“非 function 的工具协议项”，通过 **工具虚拟化**映射到 function tool 的 `tool_calls`/`role:"tool"`（具体映射由工具注册表决定）。
- `type:"reasoning"` items: preserve for reasoning+tools continuity when possible (e.g., via OpenRouter `message.reasoning_details[]` round-trip), but never stringify into normal message content. If passthrough is not supported, ignore to avoid polluting the prompt.

#### 6.3 `tools` 与工具虚拟化（重点）

约束（调研硬证据）：

- OpenRouter Chat Completions 侧稳定支持的是 `tools:[{type:"function", function:{...}}]`。
- 直接发送 `tools:[{type:"apply_patch"}]` 这类 built-in 形状会 400；少数类型（如 `web_search`）可能被 provider 特判为 server-side tool use，绕过 `tool_calls`。

因此建议：

- **对内**：始终只发送 function tools；把 built-in/MCP/自定义工具都投影为 function tools（工具虚拟化）。
- **对外**：保持 Responses 形状与 tool loop：
  - 将上游 tool_calls 翻译为 Responses output items（`function_call` 或 `*_call`）。
  - 将客户端回传的 `*_call_output`/`function_call_output` 翻译为 chat 的 `role:"tool"` message。

工具注册表（建议能力）：

- **内置工具协议**：至少提供 `apply_patch`、`shell` 等与现有探针脚本一致的 schema（见 `docs/openrouter_apply_patch_probe.py` 的 schema 示例）。
- **可扩展**：允许通过配置文件/代码注册新工具（name、description、parameters JSON schema、output 处理策略）。
- **命名冲突处理**：虚拟化工具的 function 名应与外部 tool 类型对齐，并保存“外部 tool 类型 ↔ function 名”映射；若发生命名冲突，应该尽早拒绝请求（fail fast）。

#### 6.4 Structured Outputs（JSON Schema）

映射规则（调研已给出，可直接实现）：

- Responses 请求：

```json
{
  "text": {
    "format": {
      "type": "json_schema",
      "name": "X",
      "strict": true,
      "schema": { "...": "..." }
    }
  }
}
```

- 对 OpenRouter 发送：

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "X",
      "strict": true,
      "schema": { "...": "..." }
    }
  }
}
```

降级策略：

- 若上游/模型不支持 structured outputs，返回明确错误或自动退化为普通文本（建议由配置开关控制，避免“悄悄变更语义”）。

### 7. Streaming 设计：ChatCompletions SSE → Responses SSE

目标：把 OpenRouter chat.completions 的 SSE chunk（OpenAI 兼容 `choices[].delta`）转写成 OpenAI Responses streaming events（`response.output_text.delta`、`response.function_call_arguments.delta` 等）。

#### 7.1 推荐事件子集（MVP）

为了在实现成本与兼容性之间平衡，建议 MVP 至少输出：

- `response.created`
- `response.output_item.added`
- `response.output_text.delta` / `response.output_text.done`
- `response.function_call_arguments.delta` / `response.function_call_arguments.done`
- `response.output_item.done`
- `response.completed`
- 异常时：`response.failed`

可选（更贴近官方序列但并非所有客户端都依赖）：

- `response.in_progress`
- `response.content_part.added` / `response.content_part.done`

#### 7.2 转写状态机（实现要点）

需要维护一个 streaming state（每个请求一份）：

- **Response 基本信息**：`response_id`、`model`、`created_at`。
- **文本聚合器**：累计 assistant 文本（用于发送 `output_text.done`）。
- **tool_calls 聚合器**：
  - 以 `tool_call.index` 为 key 维护：
    - `tool_call_id`
    - `function.name`
    - `arguments`（增量拼接字符串）
  - 当首次观测到某个 tool_call（或其 name/id）时，立刻发 `response.output_item.added`（创建 `type:"function_call"` 或 `type:"*_call"` item，arguments 初始为空）。
  - 每收到一段 `delta.tool_calls[i].function.arguments`，发 `response.function_call_arguments.delta`。
  - 收到 `[DONE]` 后，为每个 tool_call 发 `...arguments.done` 与 `response.output_item.done`，再发 `response.completed`。

#### 7.3 失败与超时

- 若上游在尚未输出任何事件前失败：直接返回非 200 JSON error（符合普通 HTTP 语义）。
- 若上游在已开始流式输出后失败：输出 `response.failed` 事件并关闭连接；同时在服务端日志记录上游 `x-request-id` 便于追踪。

### 8. 有状态兼容策略（`previous_response_id`）

调研结论：OpenRouter 路径 stateless，若要兼容 Responses 的会话能力，中间层必须存储上下文。

#### 8.1 存什么

建议存“归约后的 messages + 与本轮相关的工具/映射元数据”，避免下轮重复推导产生偏差：

- `messages`（chat messages，含 tool messages）
- `tools_virtualization_map`（外部 tool ↔ 内部 function）
- `model`（或 model 映射后的结果）
- 其他：`temperature/top_p/max_tokens` 等是否需要写入由产品策略决定（一般不需要，按每次请求为准）

#### 8.2 `instructions` 的特殊处理

按 OpenAI 语义：当与 `previous_response_id` 一起使用时，**上一轮 instructions 不自动沿用**。

因此建议：

- 将 `instructions` 视为 **transient**：不写入持久会话；每次请求都把当次 instructions 注入到最前 system/developer message。

#### 8.3 存储后端建议

- **开发/MVP**：进程内内存（带 TTL，避免 OOM）。
- **生产/多实例**：Redis（主流、易运维、支持 TTL）。
- **本地可复现**（可选）：SQLite（便于排障与录制回放），但不建议作为高并发生产后端。

`store:false` 策略（可选实现）：

- 若客户端请求明确 `store:false`，中间层可选择不落盘/不入库；当后续请求带 `previous_response_id` 时返回明确错误（与“无状态代理”一致）。

### 9. 错误处理、重试与降级

#### 9.1 错误对齐

建议将 OpenRouter 上游错误映射为 OpenAI 风格错误响应：

```json
{
  "error": {
    "message": "Upstream error ...",
    "type": "invalid_request_error",
    "param": null,
    "code": null
  }
}
```

并在响应头/日志中保留：

- 上游 `x-request-id`
- 本地生成的 `request_id`（便于跨系统串联）

#### 9.2 重试策略（建议）

- 仅对 **请求尚未向客户端开始流式输出** 的场景做重试（避免重复输出导致客户端状态混乱）。
- 仅对明确的瞬时错误重试：连接超时、读取超时、5xx、429（可配置）。
- 重试需做指数退避与抖动；并设置上限（最大次数/最大总耗时）。

#### 9.3 字段降级（`verbosity` 等）

对“OpenRouter/Provider 可能不支持”的字段，建议实现“失败后降级重试”的可配置策略：

- 首次按原样透传；
- 若上游报 `invalid_request` 且明确指向该字段，删除该字段重试一次；
- 仍失败则返回错误。

### 10. 配置与安全

建议使用环境变量（或 `.env`）管理：

- **上游**：
  - `OPENROUTER_API_KEY`（必需）
  - `OPENROUTER_BASE_URL`（默认 `https://openrouter.ai/api/v1`）
  - `OPENROUTER_HTTP_REFERER` / `OPENROUTER_X_TITLE`（可选，归因用）
- **本服务**：
  - `OPENBRIDGE_HOST` / `OPENBRIDGE_PORT`
  - `OPENBRIDGE_LOG_LEVEL`
  - `OPENBRIDGE_STATE_BACKEND=memory|redis`
  - `OPENBRIDGE_REDIS_URL`（若启用 redis）
  - `OPENBRIDGE_MODEL_MAP_PATH`（model 映射表路径）
  - `OPENBRIDGE_CLIENT_API_KEY`（可选：对外鉴权；适合非本机部署）

安全建议：

- 默认仅监听 `127.0.0.1`（本地代理场景更安全）。
- 若对公网暴露，必须启用客户端鉴权、限流，并避免把上游 key 透传给客户端。

### 11. 依赖选型建议（主流、现代、尽量不造轮子）

本项目本质是 **HTTP 代理 + 协议/事件转换**，不需要引入完整 agent 框架（LangChain/LangGraph）作为核心依赖；它们可作为“示例客户端/测试 harness”按需加入。

#### 11.1 Runtime（建议最小集合）

- **FastAPI + Uvicorn**：主流 ASGI 框架与服务端，生态成熟，便于做 streaming。
  - `fastapi`
  - `uvicorn[standard]`
- **HTTPX + SSE 客户端解析**：现代异步 HTTP 客户端；SSE 尽量用现成解析器避免手写边界。
  - `httpx`
  - `httpx-sse`（SSE client，避免手写 `iter_lines()` 解析）
- **SSE 服务端输出**：
  - `sse-starlette`（提供 `EventSourceResponse`，FastAPI 常用方案）
- **配置与数据模型**：
  - `pydantic>=2.x`
  - `pydantic-settings>=2.x`
- **重试**：
  - `tenacity`
- **日志**（二选一，按团队偏好）：
  - `loguru`（你常用，开箱即用）
  - 或 `structlog`（更偏结构化日志；如要接入 OpenTelemetry/ELK 可考虑）
- **有状态存储（Level 2）**：
  - `redis[hiredis]`（主流、性能好、支持 TTL）

#### 11.2 Dev/Test（建议）

- `pytest` + `pytest-asyncio`：异步测试。
- `respx`：mock httpx，上游响应/流式 chunk 可控（强烈推荐，避免自己造 mock）。
- `ruff`：现代 Python lint/format（速度快，生态主流）。
- `pre-commit`：统一代码质量门禁（可选但推荐）。

#### 11.3 可选（按需）

- **CLI**：`typer`（你常用；可用于 `openbridge serve`、`openbridge replay` 等命令）。
- **高性能 JSON**：`orjson`（可选；对大流量/高并发有收益）。
- **可观测性**：
  - `prometheus-client`（metrics）
  - `opentelemetry-sdk` + `opentelemetry-instrumentation-*`（链路追踪）
- **交互式验证/UI（非核心）**：
  - `chainlit`（用来快速做一个调试 UI，连接本地 OpenBridge，验证 tool/streaming 行为）
- **文档站点（非核心）**：
  - `mkdocs-material` + `pymdown-extensions`（与你常用栈一致）

#### 11.4 关于你常用依赖的取舍建议

- 适合直接作为本项目依赖的：`openai`（可选，用作上游 client）、`pydantic`、`pydantic-settings`、`loguru`、`tenacity`、`typer`、`pytest`、`rich`（CLI 输出可选）。
- 不建议作为核心 runtime 依赖的（除非要做 agent/流程编排）：`langchain`、`langgraph`（本项目核心是协议转换，不需要引入上层抽象）。
- 与当前仓库一致性建议：当前 `pyproject.toml` 仅有 `openai`，且探针脚本已使用 `httpx`，后续实现中建议把 `httpx` 纳入正式依赖，避免“脚本能跑但项目依赖缺失”。

### 12. 风险与边界（需要在文档中明确）

- **无法完美对齐的高级能力**：Responses 的 `include`、细粒度 logprobs/加密推理等通常无法在 ChatCompletions 路径上等价提供；需要显式降级。
- **server-side tool use 的不确定性**：像 `web_search` 可能被上游拦截为 server-side 行为，导致不走 tool loop；若要一致语义，建议统一 function 虚拟化。
- **Python 版本兼容性**：仓库当前是 `>=3.14`；若生态依赖对 3.14 支持滞后，建议将运行时版本策略调整为 `>=3.12/3.13`（以获得更广泛的第三方库支持）。

