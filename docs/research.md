## 调研报告：用中间层把 OpenAI Responses API 转成 OpenRouter Chat Completions API

更新时间：2026-01-29

### 1. 背景与目标

你的设想是做一个 **“Responses→ChatCompletions” 兼容层**：

- **本地应用**（例如 Codex）只会调用 **OpenAI Responses API**（`POST /v1/responses`），并依赖它的 `instructions`、工具调用（tool/function calling）与流式事件等语义。
- **中间层**对外暴露 OpenAI Responses API 形状；对内把请求转换为 **OpenRouter Chat Completions API**（`POST /api/v1/chat/completions`），从而让 OpenRouter 转发到 OpenAI 模型。
- **原因**：OpenRouter 的 Responses API 仍是 beta（且文档明确为 stateless），在你描述的场景里对“指令/工具调用字段等”存在对齐风险；而 Chat Completions 端更成熟，且工具调用、结构化输出等能力更完整，理论上可通过中间层弥补“形状差异”。**需要注意：Chat Completions 同样是无状态的**——无论走哪条 OpenRouter 路径，要兼容 `previous_response_id`/会话都需要中间层（或客户端）负责历史拼接/存储，差别主要在 API 形状与工具语义的成熟度。

### 2. 结论摘要（可行性）

**结论：可以做，但需要明确“支持范围”和“有状态/无状态策略”。**

- **可高保真支持的核心能力（推荐作为 MVP）**
  - **文本对话**：`input`（string 或消息数组）→ `messages`
  - **`instructions`**：映射到 `system` 消息（或拼接到已有 system 消息）
  - **Function calling / tool calling**：Responses 的 `function_call` / `function_call_output` ↔ ChatCompletions 的 `tool_calls` / `role:"tool"` 消息（可做到很接近 1:1）
  - **流式输出（SSE）**：可以把 OpenRouter 的 chat.completions 流式 chunk 转写成 OpenAI Responses 的事件流（`response.output_text.delta` / `response.function_call_arguments.delta` 等）
  - **结构化输出（JSON Schema）**：OpenRouter 已支持 `response_format: { type:"json_schema", json_schema:{...} }`，可从 Responses 的 `text.format` 做相对完整映射

- **需要明确策略 / 需要额外处理的点**
  - **OpenAI Responses 的 built-in tools / MCP tools**：在 OpenRouter **Chat Completions** 侧，`tools` 参数基本遵循 OpenAI ChatCompletions 的 tool calling 规范，**稳定可依赖的是 function tools（`type:"function"`）**。实测：`tools:[{type:"apply_patch"}]` 这类 built-in 形状会 400（提示 `tools[0].type` 必须是 `"function"` 且需要 `function` 对象）；但也存在少数类型（如 `web_search`）可能被 OpenRouter/provider **特判为 server-side 能力**直接执行（可在 `usage.server_tool_use.web_search_requests` 里看到请求计数），从而不走 `tool_calls`。因此 **built-in/MCP 不能原样透传**，但完全可以把它们当作“模型↔执行器之间协商好的协议”，用 **function tool 虚拟化（tool virtualization）**统一承载：对内统一投影为 function tools；对外再翻译回 Responses item（`*_call`/`*_call_output` 或 `function_call`/`function_call_output`），继续走 `tool_calls`/`role:"tool"` 的 loop。
    - 注：若你希望语义一致（始终走 “tool loop” 而不是 provider 特判路径），建议把 `web_search` 也做成 function 虚拟化，不依赖 `tools:[{type:"web_search"}]` 的 server-side 行为。
  - **`conversation` 与 `previous_response_id` 的语义**：Responses 原生支持会话状态；而 OpenRouter Chat Completions 是无状态，需要中间层 **自己存会话** 才能兼容（或强制客户端每次传全量历史）。
  - **Responses 的 `include` 扩展字段（如 logprobs、web_search sources、encrypted reasoning 等）**：Chat Completions 端不一定能提供同等粒度；多数只能忽略/降级。
    - Note: OpenRouter Chat Completions exposes non-standard reasoning fields (`reasoning`, `reasoning_details`) that can partially cover OpenAI Responses reasoning passthrough for supported models. See §3.4.

### 3. 两边 API 关键事实（来自官方文档）

#### 3.1 OpenAI Responses API（OpenAI 官方）

- **Endpoint**：`POST https://api.openai.com/v1/responses`
- **核心请求字段（节选）**：
  - `input`: *string 或 array*（文本/图片/文件等输入）  
  - `instructions`: *string*，“插入到上下文里的 system/developer message”；且当与 `previous_response_id` 一起使用时，“上一轮的 instructions 不会自动沿用”（方便切换系统提示词）  
  - `tools`、`tool_choice`、`parallel_tool_calls`：工具调用相关  
  - `text`: 文本输出配置（含结构化输出）  
  - `stream`: `true` 时以 SSE 输出 streaming events  

来源：OpenAI Responses API Reference（Create / Request body）`https://platform.openai.com/docs/api-reference/responses/create`（在 “List input items” 页面也能看到同一份字段说明：`https://platform.openai.com/docs/api-reference/responses/input-items`）。

- **工具调用的 Responses 形状（非常关键）**
  - 模型在 `response.output` 里返回 `type:"function_call"` item，包含 `call_id`、`name`、`arguments`（JSON 字符串）。
  - 客户端执行工具后，把结果作为 `type:"function_call_output"` item 追加回下一次 `input`，并通过 `call_id` 关联。

来源：OpenAI Function calling guide（Responses 模式）`https://platform.openai.com/docs/guides/function-calling?api-mode=responses`。

- **Responses Streaming（SSE）事件模型（节选）**
  - 生命周期：`response.created` / `response.in_progress` / `response.completed` / `response.failed` / `response.incomplete`
  - 输出 item：`response.output_item.added` / `response.output_item.done`
  - 内容片段：`response.content_part.added` / `response.content_part.done`
  - 文本增量：`response.output_text.delta` / `response.output_text.done`
  - 工具调用参数增量：`response.function_call_arguments.delta` / `response.function_call_arguments.done`

来源：OpenAI Streaming events reference `https://platform.openai.com/docs/api-reference/responses-streaming`。

#### 3.2 OpenRouter Chat Completions API（OpenRouter 官方）

- **Endpoint**：`POST https://openrouter.ai/api/v1/chat/completions`
- **鉴权**：`Authorization: Bearer <OPENROUTER_API_KEY>`  
  可选 `HTTP-Referer`、`X-Title` 用于应用归因/排行展示。  
来源：OpenRouter Authentication `https://openrouter.ai/docs/api/reference/authentication`

- **工具调用（tool calling）**
  - 请求中传 `tools`（OpenAI 兼容的 function tool shape）
  - 返回的 assistant message 包含 `tool_calls`
  - 工具结果用 `role:"tool"` 消息回传，并通过 `tool_call_id` 关联
来源：OpenRouter Tool Calling guide `https://openrouter.ai/docs/guides/features/tool-calling`

- **参数与兼容性**
  - `tool_choice` 支持：`none`/`auto`/`required`，以及强制指定某个 function  
  - `parallel_tool_calls` 支持  
  - `verbosity` 参数存在（OpenAI Responses 引入），OpenRouter 文档也将其作为可传参数  
来源：OpenRouter Parameters `https://openrouter.ai/docs/api/reference/parameters`

- **结构化输出（JSON Schema）**
  - `response_format: { type:"json_schema", json_schema:{ name, strict, schema } }`
  - 并可 `stream: true` 进行流式 structured outputs
来源：OpenRouter Structured Outputs `https://openrouter.ai/docs/guides/features/structured-outputs`

#### 3.3 OpenRouter Responses API（Beta）现状（与你的动机相关）

OpenRouter 文档明确：

- **Beta**：可能发生 breaking changes
- **Stateless only**：每次请求独立，不保存 conversation state；必须在每次请求里带全量历史

来源：OpenRouter Responses API Beta `https://openrouter.ai/docs/api/reference/responses`

#### 3.4 OpenRouter reasoning passthrough (Chat Completions extension)

OpenRouter extends the OpenAI-compatible Chat Completions schema with a unified `reasoning` config and additional response fields. This makes **reasoning round-trip** (and "keep reasoning items in context") feasible *even if you only use* `/api/v1/chat/completions`.

- **Request shape**
  - Preferred: top-level `reasoning` object (OpenRouter-normalized across providers)
  - Also supported by some SDK patterns: `extra_body.reasoning` (useful when the OpenAI SDK does not expose non-standard fields directly)
  - Common knobs include:
    - `reasoning.effort` (e.g. `low|medium|high`, model-dependent)
    - `reasoning.max_tokens` (budget for reasoning tokens, model-dependent)
  - Docs: `https://openrouter.ai/docs/best-practices/reasoning-tokens`

- **Response fields (non-stream)**
  - `choices[].message.reasoning` (optional string)
  - `choices[].message.reasoning_details[]` (optional array)
  - `reasoning_details[].type` can be:
    - `reasoning.summary` (contains `summary`)
    - `reasoning.text` (contains raw `text`, optional `signature`)
    - `reasoning.encrypted` (contains base64 `data`)
  - Docs: `https://openrouter.ai/docs/best-practices/reasoning-tokens` and `https://openrouter.ai/docs/api-reference/chat-completion`

- **Response fields (stream)**
  - `choices[].delta.reasoning_details[]` may appear in SSE chunks.
  - Docs: `https://openrouter.ai/docs/best-practices/reasoning-tokens`

- **Token accounting**
  - `usage.completion_tokens_details.reasoning_tokens` may be present for models that expose reasoning token usage.
  - Docs: `https://openrouter.ai/docs/api-reference/chat-completion`

Important caveats:

- Some models/providers (notably OpenAI o-series) may **use** reasoning internally but **do not return** reasoning tokens/text in the response. OpenRouter documents this explicitly.
- For tool calling continuity, OpenRouter recommends preserving and replaying `reasoning_details` blocks **unchanged and in the exact order** they were emitted. This aligns with OpenAI's recommendation to "keep reasoning items in context" for function calling (Responses API):
  - OpenAI reasoning guide: `https://platform.openai.com/docs/guides/reasoning#keeping-reasoning-items-in-context`

### 4. “Responses → ChatCompletions” 中间层：字段与语义映射

下面以 **“中间层对外完全模拟 OpenAI Responses API”** 为目标，给出可落地映射方案。

#### 4.1 总体策略

- **对外**：实现（至少）`POST /v1/responses`，返回 OpenAI Responses 的 response object 形状；`stream:true` 时输出 OpenAI Responses streaming events。
- **对内**：调用 OpenRouter `POST /api/v1/chat/completions`（非 streaming / streaming 两种），并把返回转回 Responses shape。

#### 4.2 请求字段映射（常用子集）

| OpenAI Responses 请求字段 | OpenRouter ChatCompletions 字段 | 处理建议 |
|---|---|---|
| `model` | `model` | **需要 model 名称映射**（例如 OpenAI 原生 `gpt-4.1` → OpenRouter 常用写法 `openai/gpt-4.1`）。建议用配置表显式映射。 |
| `instructions` | `messages[0..]` 的 `system` | OpenRouter messages roles 常见为 `system/user/assistant/tool`（若 provider/模型支持 `developer` role，也可优先映射为 `developer`）。把 `instructions` 转为最前面的 `system/developer` message（或与已有 system/developer 合并）。**重要：为对齐 OpenAI 语义，`previous_response_id` 场景下不应“自动继承上一轮 instructions”**——因此如果你做了有状态兼容，建议把“由 instructions 注入的 system/developer message”视为 **transient**，不要写入持久会话；每次请求都用当次 `instructions` 重建/覆盖。 |
| `input` (string) | `messages=[{role:"user",content:<string>}]` | 最简单路径。 |
| `input` (array items) | `messages` | 需要把 Responses “item 列表” 归约成 chat messages（见 4.3）。 |
| `tools` | `tools` | Responses 的 tool 定义可能是扁平（`{type,name,parameters,...}`）或嵌套（`{type,function:{...}}`）。中间层应同时兼容并输出 OpenRouter 期望的形状。 |
| `tool_choice` | `tool_choice` | `auto/none/required` 可直接传；强制某函数需将 Responses 的 `{type:"function", name:"x"}` 转为 `{type:"function", function:{name:"x"}}`。`allowed_tools` 需要降级（见 4.4）。 |
| `parallel_tool_calls` | `parallel_tool_calls` | 直接透传。 |
| `max_output_tokens` | `max_tokens` | 语义接近；直接映射。 |
| `temperature`,`top_p` | 同名 | 直接透传。 |
| `verbosity` | `verbosity` | 若客户端传了则**透传**；provider 不支持时可能忽略或报错，工程上可选择白名单、或在失败时降级为“删除该字段重试”。 |
| `reasoning` | `reasoning` (or `extra_body.reasoning`) | OpenAI Responses has a first-class `reasoning` object (e.g. `effort`, optional `summary`). OpenRouter Chat Completions also supports a normalized `reasoning` config and can return `reasoning_details` for some models. **Model-dependent**: some models may not return reasoning content even when reasoning is enabled. |
| `text.format` (structured outputs) | `response_format` | 需要把 Responses 的 `text.format` 映射到 OpenRouter 的 `response_format`（见 4.5）。 |
| `stream` | `stream` | 都支持 SSE；但事件协议不同，需要转写（见 4.6）。 |

#### 4.3 `input` items → `messages`：核心归约算法（支持工具调用）

OpenAI Responses 的 `input` 允许传 *string 或 array*；array 里既可以是普通 message，也可以混入之前返回的 output items（例如把 `response.output` 原样 append 回 input），这是 Codex/agent 类应用常见模式。

注意：本节同时提到两类“工具相关对象”，容易混淆：

- **请求侧 `tools[]`**：声明“有哪些工具可用”（OpenRouter Chat Completions 侧稳定可依赖的是 `type:"function"` 形状）。
- **输入/输出侧 items**：模型发起的“工具调用记录”（Responses 里是 `function_call` 或 `*_call` / `*_call_output` items）。

你可以把归约规则设计成（伪代码）：

```text
given: responses_input_items[]
result_messages = []

for each item in responses_input_items:
  if item is "message-like" (has role + content):
    append to result_messages as {role, content}

  else if item.type == "function_call":
    // 转成 assistant message 的 tool_calls
    append (or merge into last assistant tool_calls message) :
      { role:"assistant", content:null, tool_calls:[{id: item.call_id, type:"function", function:{name:item.name, arguments:item.arguments}}]}

  else if item.type == "function_call_output":
    append:
      { role:"tool", tool_call_id: item.call_id, content: (item.output if item.output is string else json.dumps(item.output)) }

  else if item.type endswith "_call":
    // built-in tools (shell_call/apply_patch_call/web_search_call/...) 也可以当作“只是工具调用”
    // 关键是把它们映射到你对内声明的 function tool 协议（tool_name_from / tool_args_from 由中间层决定）
    append:
      { role:"assistant", content:null, tool_calls:[{id: item.call_id, type:"function", function:{name: tool_name_from(item.type), arguments: json.dumps(tool_args_from(item))}}]}

  else if item.type endswith "_call_output":
    // built-in tool outputs：同样回传为 role:"tool"
    append:
      { role:"tool", tool_call_id: item.call_id, content: (tool_output_from(item) if tool_output_from(item) is string else json.dumps(tool_output_from(item))) }

  else if item.type == "reasoning":
    // OpenAI Responses may return `type:"reasoning"` output items (summary/encrypted_content) for reasoning models.
    // OpenRouter Chat Completions can carry similar information via `message.reasoning_details[]`.
    //
    // Recommendation:
    // - Preserve reasoning items for tool-calling continuity (stateful mode: store+replay; stateless mode: require client to send them back).
    // - Do NOT stringify reasoning into normal message content (it will pollute the prompt).
    // - If you do not support reasoning passthrough, you may ignore them safely (but some reasoning+tools workflows can degrade).
    preserve_reasoning_for_next_turn(item)
    continue

  else:
    // unknown item types
    ignore or reject
```

这个归约算法背后的依据：

- OpenAI Responses 工具调用输出 item 形状：`type:"function_call"` + `call_id/name/arguments`，以及回传 `type:"function_call_output"` + `call_id/output`（OpenAI 文档示例）  
  `https://platform.openai.com/docs/guides/function-calling?api-mode=responses`
- OpenRouter（OpenAI 兼容）工具调用形状：assistant message 的 `tool_calls`，以及 `role:"tool"` + `tool_call_id` 回传结果  
  `https://openrouter.ai/docs/guides/features/tool-calling`

补充约定（避免 `id`/`call_id` 写错）：

- Chat Completions 的 `tool_calls[].id` / tool message 的 `tool_call_id` **对应 Responses 的 `call_id`**（这是“工具调用关联”的关键字段）。
- Responses item 的 `id` 只是 output item 自身标识（可由中间层自生成或忽略），**不用于** tool output 的关联。

#### 4.4 `tool_choice` 的坑：`allowed_tools` 与形状差异

OpenAI Responses 支持更丰富的 `tool_choice` 形状（例如 `allowed_tools` 列表）：

- `tool_choice: "auto" | "none" | "required"`
- `tool_choice: {"type":"function","name":"get_weather"}`（强制某函数）
- `tool_choice: {"type":"allowed_tools","mode":"auto","tools":[...]}`

OpenRouter 文档明确支持 `none/auto/required` 与强制某个 function（参数页）：

`https://openrouter.ai/docs/api/reference/parameters`

**建议的兼容策略：**

- **`auto/none/required`**：直接透传
- **强制某函数**：把 `{type:"function", name:"X"}` 转成 `{type:"function", function:{name:"X"}}`
- **`allowed_tools`**：ChatCompletions 没有同名结构时，做降级：
  - 直接把 `tools` 列表过滤成 allowed 子集
  - `tool_choice` 用 `mode`（如 `auto`）对应值
  - 这样能在语义上达到“只允许某些工具”。

#### 4.5 结构化输出：Responses `text.format` ↔ OpenRouter `response_format`

OpenAI Responses 的结构化输出（json_schema）在 Responses 模式中以 `text.format` 表达（示例）：

- `POST /v1/responses` 的 body 里有 `text.format: { type:"json_schema", name, schema, strict }`  
来源：OpenAI Structured Outputs guide（Responses）`https://platform.openai.com/docs/guides/structured-outputs`

OpenRouter Structured Outputs 支持：

- `response_format: { type:"json_schema", json_schema:{ name, strict, schema } }`  
来源：`https://openrouter.ai/docs/guides/features/structured-outputs`

**建议映射：**

- 若 Responses 请求是：

```json
{
  "text": { "format": { "type": "json_schema", "name": "...", "strict": true, "schema": { ... } } }
}
```

- 则中间层对 OpenRouter 发送：

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": { "name": "...", "strict": true, "schema": { ... } }
  }
}
```

对于老式 JSON mode（`json_object`）同理映射到 OpenRouter 的 `response_format: {type:"json_object"}`（OpenRouter 参数页也明确提示仍需用 system/user 指令要求模型输出 JSON）。

#### 4.6 Streaming：把 ChatCompletions SSE 转写成 Responses SSE

OpenAI Responses streaming 事件集非常明确（包含 `response.output_text.delta`、`response.function_call_arguments.delta` 等），而 ChatCompletions 的 streaming 则以 `choices[].delta` 输出（OpenAI 兼容）。

**最实用的转写策略：**  
注：`response.in_progress` 与 `response.content_part.*` 事件是“更贴近官方事件序列”的可选层；如果你的客户端只依赖 `output_text.*` / `function_call_arguments.*`，也可以省略它们而只保留 `output_item.*` + 文本/参数事件。

- **文本 delta**：
  - 第一次收到任何文本 delta 前，先发：
    - `response.created`（含空 output）
    - `response.in_progress`（可选；更贴近官方序列）
    - `response.output_item.added`（创建一个 `type:"message"` 的 output item，content 为空）
    - `response.content_part.added`（创建一个 `type:"output_text"` part，text 为空）
  - 每次 chat chunk 里出现 `delta.content`：
    - 发 `response.output_text.delta`（把该段 content 作为 delta）
  - 结束时：
    - 发 `response.output_text.done`（拼接后的最终文本）
    - 发 `response.content_part.done`、`response.output_item.done`
    - 发 `response.completed`

OpenAI Responses streaming 事件参考：`https://platform.openai.com/docs/api-reference/responses-streaming`

- **工具调用 arguments delta**：
  - ChatCompletions streaming chunk 中如果出现 `delta.tool_calls[n].function.arguments`（可能是增量）：
    - 对应发 `response.output_item.added`，其 `item` 为 `type:"function_call"` 且 `arguments` 初始为空
    - 随后持续发 `response.function_call_arguments.delta`（把 arguments delta 逐段拼接）
    - 最终发 `response.function_call_arguments.done` 与 `response.output_item.done`

OpenAI function calling streaming 示例里给出了这组事件的真实样子（`response.output_item.added` / `response.function_call_arguments.delta/done` / `response.output_item.done`）：  
`https://platform.openai.com/docs/guides/function-calling?api-mode=responses`

### 5. 仍然存在的“无法完美对齐点”与规避建议

#### 5.1 Responses 的 built-in tools / MCP tools

第 8 章包含**更多实测证据与实现建议**。这里仅保留 TL;DR：

- **建议统一用 function tool 虚拟化承载 built-in/MCP/function**，让中间层始终走 `tool_calls`/`role:"tool"` 的 tool loop（对外再翻译回 Responses item）。
- **built-in 形状在 Chat Completions 下大多不稳定**：可能 4xx（如 `apply_patch` 实测 400），也可能被 provider 特判为 server-side 能力（如 `web_search`），从而绕过 `tool_calls`。

#### 5.2 会话状态：`previous_response_id` / `conversation` / `store`

OpenAI Responses 可以通过 `previous_response_id` / `conversation` 进行 **状态化多轮**；而 OpenRouter 的 Responses Beta 与 Chat Completions 都是 **stateless**（每次必须带全量历史）：
`https://openrouter.ai/docs/api/reference/responses`

如果你希望兼容那些依赖 `previous_response_id` 的客户端：

- **中间层必须有状态**：保存每个 `resp_id` 对应的“归约后的 messages + tools + tool_choice 等”，在下一次请求携带 `previous_response_id` 时自动补全上下文。
- **`instructions` 必须按 OpenAI 语义处理**：上一轮 `instructions` **不应自动沿用**。因此建议不要把“由 instructions 注入的 system message”写入持久历史，而是在每轮请求时用当次 `instructions` 重新注入/覆盖。
- 若客户端使用 `store:false`（OpenAI Responses 的含义是 OpenAI 不保存响应），中间层也可选择 **不保存**，并在下一次 `previous_response_id` 时返回错误，行为与“无状态代理”一致。

#### 5.3 `include` 扩展字段与高级输出

OpenAI Responses 的 `include` 可以要求返回更多细节（如 logprobs、web_search sources、encrypted reasoning 等）。ChatCompletions 通常无法提供同等粒度，建议：

- **显式忽略** `include` 并在响应 `metadata` 中回写“已忽略的 include 列表”
- 或 **只支持子集**（例如 OpenRouter 若支持 logprobs 时再映射）
  - For reasoning models, consider supporting the reasoning-related subset by mapping OpenRouter `message.reasoning_details[]` to Responses `type:"reasoning"` items (summary/encrypted content), when available. This is model/provider-dependent (and may be absent for OpenAI o-series).

### 6. 推荐的中间层形态（工程落地建议）

#### 6.1 API 形态

- **必须实现**
  - `POST /v1/responses`（含 `stream:false/true` 两种）
- **按需实现（取决于客户端是否调用）**
  - `GET /v1/responses/{response_id}`：若你做了“有状态存储”，可实现；否则返回 404/501
  - `DELETE /v1/responses/{response_id}`：同上

#### 6.2 必要配置

- **model 映射表**：例如
  - `gpt-4.1` → `openai/gpt-4.1`
  - `gpt-5.2-codex-max` → `openai/gpt-5.2-codex-max`（仅示意，需以 OpenRouter models 列表为准）
- **OpenRouter headers**
  - `Authorization: Bearer ...`
  - 可选 `HTTP-Referer`、`X-Title`

#### 6.3 兼容性分级（建议写进 README/对外文档）

- **Level 0（最稳）**：`input` 为 string，纯文本输出，不用 tools，不用 streaming
- **Level 1（推荐 MVP）**：支持 tools/function calling + tool results loop（含 streaming）
- **Level 2（高级）**：支持 `previous_response_id`（需要中间层存储会话）+ structured outputs json_schema
- **Level 3（内建工具协议化）**：通过 function tool 虚拟化支持 Responses built-in/MCP 工具（`shell`/`apply_patch` 已实测可用）；其他工具取决于你是否提供对应的执行环境（搜索、向量库、沙箱、浏览器/截图等）。

### 7. 附：关键形状对照（摘录）

#### 7.1 OpenAI Responses 工具调用 item（OpenAI 文档）

来源：`https://platform.openai.com/docs/guides/function-calling?api-mode=responses`

- 模型 tool call 输出（出现在 `response.output`）：

```json
{
  "id": "fc_12345xyz",
  "call_id": "call_12345xyz",
  "type": "function_call",
  "name": "get_weather",
  "arguments": "{\"location\":\"Paris, France\"}"
}
```

- 客户端回传 tool output（下一次请求的 `input` 里 append）：

```json
{
  "type": "function_call_output",
  "call_id": "call_12345xyz",
  "output": "{\"temperature\":25,\"unit\":\"C\"}"
}
```

#### 7.2 OpenRouter ChatCompletions 工具调用（OpenRouter 文档）

来源：`https://openrouter.ai/docs/guides/features/tool-calling`

- assistant message tool_calls：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "search_gutenberg_books",
        "arguments": "{\"search_terms\":[\"James\",\"Joyce\"]}"
      }
    }
  ]
}
```

- tool result message：

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "[{\"id\":4300,\"title\":\"Ulysses\"}]"
}
```

---

如果你下一步希望我把这份“研究结论”继续落实成一个可运行的中间层原型（例如 Node/Fastify 或 Python/FastAPI），我可以在这个 repo 里直接搭一个最小实现：`POST /v1/responses` → OpenRouter `/api/v1/chat/completions`，并覆盖 tools + streaming 的转换。

### 8. OpenAI built-in tools：现状（已实测）与推荐方案

这部分做一次“破坏性更新”：**在我们的中间层语境里，built-in/MCP 并不“天然只能 server-side”。工具的本质是协议；难点是 OpenRouter Chat Completions 的请求侧主要支持 function tools（少数 built-in 类型可能被特判走 server-side），因此推荐统一用 function 虚拟化承载一切工具。**

#### 8.1 已观测到的 OpenRouter 行为（硬证据）

我们用仓库里的探针脚本 `docs/openrouter_apply_patch_probe.py`（通过 `uv run`）得到如下事实：

- **built-in tool 形状直传（apply_patch）会被拒绝**
  - 请求：`tools:[{"type":"apply_patch"}]`
  - 响应：HTTP 400，错误提示 `tools[0].type` 期望 `"function"`，且 `tools[0].function` 期望对象

- **function tool 虚拟化稳定产出 tool_calls（apply_patch / shell）**
  - non-stream：返回 `choices[0].message.tool_calls[0].function.arguments`（JSON 字符串，可直接 `json.loads`）
  - stream：`choices[0].delta.tool_calls[*].function.arguments` 为 **增量拼接**（需要按 index 拼接重建）

- **web_search 是个例外：可能被 OpenRouter 当作 server-side 能力处理**
  - 请求：`tools:[{"type":"web_search"}]`（built-in 形状）
  - 现象：HTTP 200 但 `choices[0].message.tool_calls == null`；同时 `usage.server_tool_use.web_search_requests == 1`
  - 含义：这类工具不一定走 `tool_calls`/`role:"tool"` loop，更像在 OpenRouter 侧被拦截执行；如果你需要“纯传话筒 + tool loop”的一致语义，建议把 `web_search` 也做成 function 虚拟化（不要依赖 provider 的特殊拦截路径）。

#### 8.2 推荐的“统一工具模型”（适配 Codex/Responses 客户端）

- **把所有工具都视为协议**：无论它叫 built-in/MCP/function，本质都是“模型输出结构化 call → 执行器运行 → 回传结构化结果”。
- **对内统一为 function tools**：对 OpenRouter `/api/v1/chat/completions` 只发送 `type:"function"` 的 tools（tool virtualization），并强制模型通过 `tool_calls` 发出调用。
- **对外保持 Responses 形状**：中间层把 function `tool_calls` 翻译回客户端期望的 Responses item（`function_call` 或 `*_call`），并把客户端回传的 `function_call_output` / `*_call_output` 翻译为 `role:"tool"` message 继续回传给 OpenRouter，直到获得最终 assistant 输出。

#### 8.3 “能不能支持”的真正约束：不是 API，而是执行环境

function 虚拟化解决的是“接口形状/传话筒”的问题，剩下的主要是工程成本（你是否提供执行器）：

- `shell` / `apply_patch`：执行器通常就是 Codex/本地集成 → 成本低（已实测可用）
- `web_search`：可以让执行器自己搜（function 虚拟化），也可以选择依赖 OpenRouter 的 server-side web_search（但这时不走 tool_calls）
- `file_search` / `code_interpreter` / `computer_use_preview`：也能协议化，但你需要提供对应的检索库、沙箱执行、浏览器/截图环境等

#### 8.4 Codex (Responses API) tool specs: `apply_patch` schemas and built-in tool types

Codex exposes `apply_patch` in two different tool shapes (selected by `apply_patch_tool_type`):

- **Freeform / custom tool (`tools[].type="custom"`)**: the tool argument is not JSON; it is a raw patch text constrained by a Lark grammar (`tool_apply_patch.lark`).
- **Function tool (`tools[].type="function"`)**: JSON arguments with exactly one required field:
  - `input: string`
  - `additionalProperties: false`

`apply_patch` can also be invoked as a **shell command** because Codex CLI places an `apply_patch` executable in `PATH` (arg0-dispatch). When both are available, providing `apply_patch` as a dedicated tool is the preferred path.

If "built-in tool type" means a Responses tool whose `tools[].type` is **not** `"function"`, Codex uses:

- `web_search`
- `local_shell`

No direct usage was found for `file_search`, `computer_use`, `code_interpreter`, `image_generation`, or `mcp` as Responses built-in tool types.

### 9. 实验脚本：探测 OpenRouter Chat Completions 的 tool_calls / server-side tool use

仓库里提供了探针脚本：`docs/openrouter_apply_patch_probe.py`。它**不会在本地执行任何工具**，只负责强制模型“发出一次工具调用”，并把 raw JSON / SSE 打出来，便于观察；但当你用 `--builtin-tools` 探测某些类型（尤其 `web_search`）时，OpenRouter/provider **可能会在服务端执行并产生额外消耗/计费**。

- **function 虚拟化是否产出 `tool_calls`**（以及 streaming 下 arguments 如何增量输出）
- **built-in 形状是否被拒绝**、或是否被 OpenRouter/provider 拦截成 server-side tool use（例如 `web_search`）

常用运行方式（需要环境变量 `OPENROUTER_API_KEY`）：

```bash
export OPENROUTER_API_KEY="..."

# 1) 默认：function 虚拟化 apply_patch
uv run python docs/openrouter_apply_patch_probe.py

# 2) 探测其他工具（function 虚拟化）
uv run python docs/openrouter_apply_patch_probe.py --tool shell
uv run python docs/openrouter_apply_patch_probe.py --tool web_search

# 3) streaming：观察 delta.tool_calls[].function.arguments 的增量拼接
uv run python docs/openrouter_apply_patch_probe.py --tool apply_patch --stream

# 4) built-in 形状直传：观察是否 4xx 或被 server-side 拦截（注意：web_search 可能比较贵）
uv run python docs/openrouter_apply_patch_probe.py --tool apply_patch --builtin-tools
uv run python docs/openrouter_apply_patch_probe.py --tool web_search --builtin-tools

# 5) 自定义“工具协议”（证明“工具=协议”，由模型与应用协商）
uv run python docs/openrouter_apply_patch_probe.py \
  --tool my_custom_tool \
  --schema-json '{"type":"object","properties":{"payload":{"type":"string"}},"required":["payload"],"additionalProperties":false}' \
  --args-json '{"payload":"hello"}'
```

你要重点观察的字段：

- **function 虚拟化（non-stream）**：`choices[0].message.tool_calls[0].function.arguments`
- **function 虚拟化（stream）**：每个 chunk 的 `choices[0].delta.tool_calls[*].function.arguments`（通常是 **增量拼接**）
- **server-side 工具路径（如 web_search）**：`usage.server_tool_use.*`（可能存在请求计数，但 `tool_calls` 为空）
