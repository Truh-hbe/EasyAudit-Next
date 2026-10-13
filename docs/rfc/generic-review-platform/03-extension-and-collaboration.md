# 03 通用扩展与协作机制设计

- 状态：提案（RFC），待维护者拍板
- 基线：`origin/main` `5a2804b`（2026-10-13）
- 相关：[README](README.md) · [01 现状与断层](01-current-state-and-gaps.md) · [02 元模型](02-meta-model.md) · [04 路线图](04-roadmap-and-dod.md)
- 本文涉及的实体、不变量与锁序以 [02](02-meta-model.md) 为准；本文说明它们如何被元数据驱动、如何协作、如何外发与导入导出。

## 1. 元数据驱动机制

### 1.1 总体思路

场景差异写成**不可变的声明式文档**。文档由内核里的**版本化引擎**解释，引擎实现现有的 `ScenarioPolicy` Protocol（`src/easyaudit_next/review_core/domain/scenario_registry.py:22-67`），所以应用服务、锁内授权、CAS 和 Activity 写入都不用改。文档能做的事有边界：只能在内核规定的**迁移包络**内选择和命名迁移，只能引用**权限词表**中的权限，只能使用**守卫库**中的守卫和**字段类型库**中的类型（[02 §9 D1–D3](02-meta-model.md#9-关键决策)）。

### 1.2 场景文档格式 `easyaudit.scenario/1`（示意，中性措辞）

```json
{
  "format": "easyaudit.scenario/1",
  "key": "sample_review",
  "version": 2,
  "name": "示例审查",
  "roles": {
    "case":    [ { "key": "lead", "label": "审查组长", "actor_kinds": ["user"], "via": ["direct"], "creator": true },
                 { "key": "auditor", "label": "审查员", "actor_kinds": ["user"], "via": ["direct"] },
                 { "key": "reviewer", "label": "复核员", "actor_kinds": ["user"], "via": ["direct"] } ],
    "finding": [ { "key": "owner", "label": "整改负责人", "actor_kinds": ["user"], "via": ["direct"] },
                 { "key": "responsible_department", "label": "责任部门", "actor_kinds": ["department"], "via": ["department_membership"] } ],
    "action":  [ { "key": "primary", "label": "主要执行人", "actor_kinds": ["user"], "via": ["direct"] } ],
    "worksheet": [ { "key": "respondent", "label": "填写方", "actor_kinds": ["user", "department"], "via": ["direct", "department_membership"] } ]
  },
  "grants": {
    "create_case":        [ { "scope": "organization", "roles": ["active_user"] } ],
    "view_case":          [ { "scope": "case", "roles": ["lead", "auditor", "reviewer"] },
                            { "scope": "finding", "roles": ["owner"] },
                            { "scope": "finding", "roles": ["responsible_department"], "via": "department_membership" },
                            { "scope": "action", "roles": ["primary"] } ],
    "manage_case_members":[ { "scope": "case", "roles": ["lead"] } ],
    "fill_worksheet":     [ { "scope": "case", "roles": ["lead", "auditor"] },
                            { "scope": "worksheet", "roles": ["respondent"] } ],
    "step:final_review":  [ { "scope": "case", "roles": ["reviewer"] } ]
  },
  "case": {
    "form": { "schema": { "type": "object", "additionalProperties": false,
                          "required": ["scope_note"],
                          "properties": { "scope_note": { "type": "string", "maxLength": 500, "x-ea-type": "long_text" } } },
              "ui": { "order": ["scope_note"], "labels": { "scope_note": "范围说明" } } },
    "transitions": [
      { "action": "schedule", "from": "draft", "to": "scheduled", "permission": "transition_case", "label": "排期" },
      { "action": "finish_fieldwork", "from": "in_progress", "to": "awaiting_closure", "permission": "transition_case",
        "label": "完成现场工作", "guards": [ { "use": "worksheets_completed" }, { "use": "nonconformities_resolved" } ] }
    ]
  },
  "finding": {
    "dispositions": [
      { "key": "requires_action", "label": "需整改", "track": "rectify_and_verify", "default_severity": "medium",
        "issue_guards": [ { "use": "participants_present", "params": { "roles": ["owner", "responsible_department"] } } ] },
      { "key": "record_only", "label": "仅记录", "track": "acknowledge", "acknowledge_permission": "acknowledge_finding" }
    ],
    "verification": { "steps": [ { "key": "final_review", "label": "复核", "permission": "step:final_review" } ] }
  },
  "submissions": {
    "rectification_plan":       { "schema": { "...": "字段 profile" }, "ui": { "sections": [ { "title": "整改计划", "fields": ["..."] } ] } },
    "rectification_completion": { "schema": { "...": "..." }, "ui": { "...": "..." } },
    "verification_reject":      { "schema": { "...": "..." } }
  },
  "worksheet_policy": { "respond_in": ["in_progress"], "allowed_templates": ["*"] },
  "recipients": { "finding_rectification": "submit_rectification", "action_execution": "update_assigned_action", "case_deadline": "transition_case" },
  "notifications": [
    { "on": "finding.rejected", "to": [ { "scope": "finding", "roles": ["owner"] } ], "category": "needs_my_action" },
    { "on": "finding.submitted_for_verification", "to": [ { "permission": "step:final_review" } ], "category": "needs_my_action" }
  ],
  "examples": [
    { "name": "缺少负责人时不能签发", "entity": "finding", "state": "open", "disposition": "requires_action",
      "facts": { "participant_roles": ["responsible_department"] }, "actor_grants": { "case": ["lead"] },
      "command": "issue", "expect": { "violation": "finding.missing_participant_roles", "params": { "roles": ["owner"] } } }
  ]
}
```

### 1.3 Schema 语言：JSON Schema 受限 profile + UI Schema（决策 D5）

- **选择**：数据 Schema 只使用 JSON Schema 2020-12 的一个子集：
  - 允许的关键字：`type`、`properties`、`required`、`additionalProperties:false`（强制）、`maxLength`/`minLength`、`minimum`/`maximum`、`enum`（或 `oneOf` + `const` + `title`）、`items`/`minItems`/`maxItems`/`uniqueItems`、`format: date|date-time`，外加 `x-ea-*` 扩展关键字。
  - 禁止的关键字：`$ref`、`if/then/else`、`pattern`、`patternProperties`、`allOf`/`anyOf`。

  UI Schema 单独描述呈现方式。后端用纯 Python、前端用 TS 各实现一个校验器，两端共享同一套一致性语料。
- **理由**：
  - 这样写出的文档仍是合法的 JSON Schema，可以随导出包交给外部系统做结构校验。
  - 禁用正则，就不会出现 ECMA 与 Python `re` 方言不一致的问题。
  - 错误能稳定映射到现有的 `FieldErrorCode`（`src/easyaudit_next/rules.py:69-79`），前端已有的中文映射可以直接复用。
  - 不引入新依赖。
- **被否决**：
  - ①完整 JSON Schema + `jsonschema`/`ajv` + `@rjsf/antd`：rjsf 自带一整套表单基础设施，与 design.md 的 `Form.Item` 规范冲突；`pattern` 在前后端的方言不一致；错误码不可控。
  - ②Pydantic `create_model`：前端无法使用，又会形成两个真相来源。

**字段类型库**（内核封闭集合）：

| `x-ea-type` | 数据形态 | antd 控件（遵循 [design.md](../../design.md)） | 字段错误码（沿用 `FieldErrorCode`） |
|---|---|---|---|
| `text` / `long_text` | string；首尾有空白即拒绝（与 @1 的 `padded` 一致） | `Input` / `Input.TextArea` | `required`、`padded`、`too_long`、`too_short` |
| `integer` | integer | `InputNumber` | `range`、`invalid` |
| `decimal` | 十进制字符串 + `x-ea-precision`；min/max 也用字符串 | `InputNumber stringMode` | `range`、`invalid` |
| `choice` | 枚举 | 选项 ≤ 4 个用 `Radio.Group`，否则用 `Select`（`docs/design.md:127`） | `invalid_choice` |
| `multi_choice` | 枚举数组 | `Checkbox.Group` / `Select mode="multiple"` | `invalid_choice`、`too_short`、`too_long` |
| `boolean` | boolean | `Radio.Group`（是/否） | `invalid` |
| `date` / `datetime` | `date` / `date-time` | `DatePicker` / `ui/ShanghaiDateTimePicker` | `invalid_datetime` |
| `user_ref` / `department_ref` | uuid | `Select showSearch` + 服务端授权的候选接口 | `invalid`（服务端另行校验同组织、是否活跃） |
| `evidence_refs` | uuid 数组 | 同 Case 证据选择器 | `invalid` |

为 `additionalProperties` 新增 `FieldErrorCode.UNKNOWN_FIELD`，按"只增不改名"的规则同步前端映射。

**UI Schema** 包含：`order`、`sections`（分段标题与所含字段）、`labels`、`help`、`placeholder`（只作示例）、`widget`（只能从上表中选）。**不允许**颜色、CSS、HTML 或脚本。

**前后端一致性**：
- 后端校验器为 `review_core/domain/definition/field_profile.py`，前端为 `web/src/metadata/fieldProfile.ts`。
- 两端共享一致性语料 `tests/fixtures/field-profile/*.json`，每个用例是"schema + value → 期望的 errors[]"，pytest 和 vitest 都跑。
- **只有服务端的校验结论算数**，前端校验只用于即时反馈（`docs/architecture.md:205`）。

### 1.4 守卫库（内核封闭集合，首批）

| 守卫 | 参数 | 所需事实（内核在锁内加载） | 违规码 | @1 是否使用 |
|---|---|---|---|---|
| `reason_required` | — | reason | `request.invalid`，`errors[reason:required]` | 是 |
| `participants_present` | `roles[]` | Finding 参与方的角色集合 | `finding.missing_participant_roles` | 是 |
| `case_lifecycle_in` | `states[]`、`operation` | Case lifecycle | `finding.invalid_case_lifecycle` | 是 |
| `disposition_in` | `dispositions[]`；可选 `code`，只能取现有 `RuleCode` 中的兼容别名 | `disposition_key` | 默认 `finding.disposition_mismatch`；@1 使用 `finding.issue_requires_nonconformity` / `finding.accept_requires_observation` | 是 |
| `all_findings_terminal` | — | 处于终态的 Finding 计数 | `case.close_blocked_by_open_findings` | 内核强制 |
| `actions_ready_for_verification` | — | 未取消整改项的数量与状态 | `finding.verification_requires_actions[_done]` | 内核强制 |
| `worksheets_completed` | — | 底稿完成情况摘要 | `case.worksheets_incomplete` | 否（新增） |
| `nonconformities_resolved` | — | `fail` 项的关联或豁免情况 | `case.unresolved_nonconformities` | 否（新增） |
| `plan_approved` | `step` | 本轮整改中计划审批步骤的结果 | `submission.plan_not_approved` | 否（新增） |
| `prior_steps_approved` | — | 本轮验证中各步骤的结果 | `verification.steps_pending` | 否（新增） |

**准入规则**（写进 ADR-0007）：新守卫必须是纯函数，只读取内核声明过的事实；违规码要登记进 `RuleCode`，并有前端映射；必须有单元测试。守卫之间只能用 AND 组合，v1 不支持 OR，也不支持嵌套表达式。新增守卫要通过代码 PR，不能靠文档自行定义。

### 1.5 发布、版本与可测试性

**发布流程**：草稿 → 校验 → 预览 → 发布 → 退役。入口有两个：CLI（`validate-scenario`、`publish-scenario --file`）和管理 API。两者用的是同一个校验器。

**发布时的静态校验**：

1. 用格式 v1 的元 Schema 校验文档。
2. 解析所有引用：角色；权限（词表加 `step:*`）；守卫名与参数类型；表单 profile；处置轨道。
3. 包络一致性：每条迁移都在包络内。内核强制守卫不能被移除；文档没写的，引擎会自动附加。
4. 图检查：每个非终态至少有一条出边，并且有某个角色能执行它；终态可达；每条处置轨道完整。
5. 管理者检查：存在创建者角色，且它拥有 `manage_case_members`（对应不变量 I9）。
6. 权限覆盖：每个内核命令要么有授权表达式，要么在文档中显式标为 `disabled`。
7. 执行文档中的 `examples`，全部通过才允许发布。
8. 输出结构化错误列表（`path`、`code`、`params`），供 CLI 和管理界面展示。

**版本与绑定**：
- 已发布的文档不可变，按 sha256 内容寻址。Case 只引用 `scenario_version_id`，不复制文档，详见 [02 D3](02-meta-model.md#d3-版本化发布与绑定)。
- 引擎按文档格式的主版本分派解释器。同一格式版本内，已有守卫与字段类型的语义保持冻结。

**可测试性**（落实 ADR-0003 的"可测试"）：

| 层 | 测试 |
|---|---|
| 守卫库、字段 profile | 单元测试；字段 profile 的一致性语料，Python 和 TS 两端都跑 |
| 引擎 | 属性测试：对任意合法文档，引擎都不会产生包络外的迁移，内核强制守卫始终生效 |
| 单份文档 | 发布时执行 `examples`；仓库内置场景库的文档在 CI 中再跑一遍 examples 和金样判决表（golden decision table） |
| @1 等价性 | 差分测试（[02 D4](02-meta-model.md#d4-现有场景与数据的无损迁移)） |
| 引擎演进 | 每份已发布的内置文档都有金样判决表；任何引擎改动只要让金样变了，CI 就失败 |
| 端到端 | 现有 `tests/integration/*` 和 `web/tests/browser/real-*.spec.ts` 不改断言，全部通过 |

### 1.6 可执行命令清单（affordances，属于决策 D15）

Case、Finding、Action、Worksheet 的 GET 响应新增 `available_commands` 字段：

```json
[ { "command": "issue", "label": "签发发现项", "mode": "direct", "form": null,
    "ready": false, "blocked_by": [ { "code": "finding.missing_participant_roles", "params": { "roles": ["owner"] } } ] },
  { "command": "void", "label": "作废", "mode": "reason", "ready": true, "blocked_by": [] } ]
```

计算方法：取当前状态下、包络内已启用的边，用 `authorization.allows` 过滤，再在锁外评估守卫，得出 `ready` 和阻塞原因。这只是给界面的提示，真正写入时仍在锁内完整复核（`docs/design.md:249`）。有了它，前端不必再复刻状态机（01 F3），声明式场景也不需要额外的前端代码。

## 2. 结构化整改与协作（决策 D10）

### 2.1 整改提交表单（元数据定义）

- 文档的 `submissions.*` 用字段 profile 定义各类提交的表单：整改计划、整改完成、复核通过、复核驳回、计划审批意见。分段结构由 `ui.sections` 决定，**不内置任何方法论字段**。@1 文档里的 `root_cause`、`comment` 只是 @1 自己的选择，不是内核概念。
- 内核保留键 `stage`、`result`、`step` 由命令决定，客户端不能填；如果客户端填了，引擎会拒绝或覆盖。
- 提交可以引用同 Case 的证据（`evidence_refs` 字段）。引用会在同一事务内写成 `evidence_attachments(submission_id)`（不变量 E3），所以提交和它引用的证据作为同一个不可变事实一起落库。
- 历史提交按 Case 所绑定版本的表单来解释（`describeSubmission` 改由文档驱动）。
- 整改项表单：`action_items` 新增 `scenario_data`，由文档的 `action.form` 定义（例如完成要求、交付物说明），对应 01 B13。

### 2.2 多角色复核（不新增状态）

- 文档声明有序的 `verification.steps`，每一步对应一个 `step:<key>` 权限。
- 在 `verifying` 状态内，每一步的结论都是一条 Submission（`purpose=verification`，`payload.step=<key>`）：
  - 中间步骤通过时 `target_lifecycle = verifying`，复用 `SubmissionDecision` 已经支持的"不改状态"；
  - 末步通过时进入 `closed`；
  - 任一步驳回时回到 `rectifying`。
- "轮次"以最近一次整改完成提交为锚点。重新提交整改完成后，之前各步的通过全部作废。守卫 `prior_steps_approved` 只看当前轮次。
- 整改计划审批同理：可选步骤 `plan_review` 的通过或退回只写 Submission，不改 Finding 状态。如果文档在整改完成提交上配置了 `plan_approved` 守卫，计划未获批时不能提交完成。
- 工作台的"待我复核"由"`verifying` + `verify_finding`"改为"`verifying` + 持有当前待办步骤的 `step:*` 权限"，仍是读侧投影。
- **被否决**：给 Finding 增加 `plan_review`、`second_review` 之类的状态。这会改动内核、读侧和导出，而且每增加一个步骤都要再改一遍。

### 2.3 讨论与评论（不改变状态）

- `comments` 可以挂在 Case、Finding、Action 和底稿项上（互斥弧 + Case 复合 FK）。只支持一层回复（`reply_to_id`），支持 `@提及`（`comment_mentions`），评论可以挂载证据（`evidence_attachments.comment_id`）。正文是纯文本，前端按文本渲染，不解析 HTML。
- 评论不可修改，只能追加。撤回也是追加一条 `comment_retractions`；读侧把正文显示为"该评论已撤回"，审计导出中是否保留原文见 Q12。
- **评论不是 Activity**。Activity 记录状态和责任变化，用于审计；评论是协作内容。读侧提供合并时间线 `GET /{target}/timeline`，把 Activity 和评论按时间合并；分页和授权按目标构造。
- **为什么能减少驳回**：需要对方补材料时，复核员先发一条评论提醒对方，可以附上证据，不必驳回、退回 `rectifying` 再让对方重新提交。只有给出结论性的"不通过"时才走驳回。
- 评论授权：按目标构造上下文，并需要 `comment` 权限。撤回他人评论需要 `moderate_comments`。
- **被否决**：
  - ①把评论写进 Activity：噪声会淹没审计事实。
  - ②支持富文本：XSS 面扩大，导出与渲染也更复杂。

### 2.4 通知补全

签发、驳回、通过、重开、被提及、底稿指派都纳入规则驱动的通知（§3），这样被驳回的人也能收到提示（01 §2 #5）。

## 3. 通知总线（决策 D11）

### 3.1 链路

```text
命令事务（一个请求一个事务）
  ├─ 业务写入 + Activity（领域事件，已有）
  ├─ EventRouter.route(mutation_result)        # collaboration 模块，规则来自场景文档
  │    ├─ 解析收件人（按当时的关系；部门展开为当时的活跃成员）
  │    ├─ 写 notifications（站内通知，已有唯一约束去重）
  │    └─ 按用户偏好与联系方式写 outbound_messages(channel=email, origin_notification_id)
  └─ 按组织的 Webhook 订阅写 outbound_messages(channel=webhook, origin_activity_id)
提交

systemd timer（每分钟）→ 一次性容器 `easyaudit-next dispatch-outbound --max-batch 200 --max-seconds 50`
  ├─ 短事务：SELECT … FOR UPDATE SKIP LOCKED LIMIT n（pending 且已到期，或租约已过期）→ 置为 in_flight 并写 lease_until → 提交
  ├─ 在事务外发送（SMTP / HTTPS；连接与读取超时显式配置，默认 10 秒）
  └─ 短事务：成功 → delivered；失败 → attempts+1，按退避设置 next_attempt_at，超过上限 → dead；last_error_class 只记类名
```

### 3.2 规则

- **与现有架构规则一致**：
  - Web 进程不运行任何调度器（`docs/architecture.md:193`）。分发器和提醒 sweep 一样由外部 timer 驱动，`check_architecture.py` 禁止 Web 进程 import 它。
  - 运行记录复用 `scheduler_runs`，`job_key=outbound_dispatch`；用 `scheduler-status --job outbound_dispatch` 监控新鲜度。
- **不引入新基础设施**：PostgreSQL 本身就是队列。多次运行有重叠时，`SKIP LOCKED` 加租约保证同一条消息不会被重复领取。SMTP 用标准库 `smtplib`，HTTP 用标准库或已有依赖。
- **幂等**：
  - outbox 行的 id 就是投递 id，邮件里放在 `Message-ID`，Webhook 放在请求头 `X-EasyAudit-Delivery`，接收方据此去重。
  - 入队去重由唯一约束裁决（[02 不变量 O1](02-meta-model.md#4-实体与不变量)），不先查后插。
- **退避与死信**：
  - 依次间隔 1m、5m、30m、2h、12h；6 次失败后转为 `dead`。
  - `outbound-status` CLI 输出积压量、最老的 pending 和 dead 数量，供监控告警。
  - 运维可以用 `retry-outbound --id … | --endpoint … --since …` 把 dead 消息重新入队（重置 attempts，写平台审计）。
  - 管理界面上的"重新投递"按钮在 CLI 稳定后再做。
- **路由规则分两层**：
  - **场景文档**的 `notifications` 定义业务语义：什么事件通知谁。它和收件人意图在同一层，随版本冻结。
  - **组织配置**定义送达方式：通道、偏好、端点。
  - 现有 4 种站内通知作为 @1 文档里的规则保留。`NotificationKind` 扩展为"类别 + 事件键"；中文文案仍在读侧按事件键映射，不写进通知行（`docs/architecture.md:186`）。
- **联系方式与偏好**：
  - `user_contact_points`：固定字段。管理员录入的邮箱视为已验证；用户自助修改需要验证码，留到后续再做。
  - `user_notification_preferences(category, channel, enabled)`：类别有 `needs_my_action`、`assignment`、`reminder`、`mention`、`fyi`。站内通知始终开启；邮件默认只对 `needs_my_action` 和 `mention` 开启。
- **邮件内容**：
  - 默认只含事件类别和站内深链接，**不带对象标题**。理由和站内通知不写标题相同，而且邮件发出后无法撤回。
  - 发送前重新校验收件人是否仍然活跃、是否仍能看到目标；不满足就跳过，记为 `delivered_skipped`。
  - 是否允许邮件带标题，见 Q3。
- **Webhook**：
  - 端点是组织级的，由 `system_admin` 管理，变更写平台审计。
  - 请求为 `POST`，正文是 JSON 薄事件 `{id, type, occurred_at, organization_id, subject:{kind,id}, links}`。
  - 签名头：`X-EasyAudit-Timestamp`，以及 `X-EasyAudit-Signature: v1=hex(HMAC-SHA256(secret, ts + "." + body))`。接收方应拒绝时间偏差超过 5 分钟的请求。
  - **密钥派生**：`secret = HMAC(主密钥文件, endpoint_id ‖ secret_version)`。数据库和备份里都没有明文密钥；轮换时把 `secret_version` 加 1；密钥只在创建时向管理员展示一次。
- **SSRF 与出网**：
  - 只允许 HTTPS；目标主机必须在 `OUTBOUND_WEBHOOK_ALLOWED_HOSTS` 白名单里；DNS 解析后再核对一次；不跟随重定向。
  - 分发器容器单独接入新的 `outbound` 网络（非 internal），API 容器不需要出网。
  - `tests/unit/test_deploy_compose.py` 增加断言：只有 dispatcher 在 `outbound` 网络上。
- **被否决**：
  - ①Redis 或其他消息中间件：属于新基础设施，违反 `docs/architecture.md:303`。
  - ②在 Web 进程里起后台线程或用 `BackgroundTasks`：多 worker 时会重复执行，重启时会丢失，违反调度规则。
  - ③分发器按 Activity 的 `occurred_at` 或 id 游标轮询：并发事务的提交顺序与 id、时间顺序不一致，晚提交的事件会被游标跳过；而且收件人到分发时才解析，违反"在当时解析"（`docs/architecture.md:201`）。
  - ④常驻 worker 加 `LISTEN/NOTIFY`：延迟更低，但多一个常驻进程要运维，留作 Q4。

## 4. 导入导出（决策 D12）

### 4.1 Case 卷宗导出

接口为 `GET /api/v1/review-cases/{id}/dossier`，需要 `export_case` 权限。

```text
dossier-<case_id>-<时间戳>.zip
  manifest.json      # format=easyaudit.case-dossier/1、generated_at、as_of、organization、case、
                     # scenario key@version + 文档 sha256、模板版本 sha256 列表、release、
                     # 每个文件的 sha256、导出者、授权过滤说明
  checksums.sha256   # 与 manifest 一致，可直接用 `sha256sum -c` 校验
  case.json          # Case、成员、计划引用、scenario_data（附字段标签）
  worksheets.json    # 分组、底稿项（定义快照 + 当前响应 + 修订历史）
  findings.json      # 处置、来源项、参与方、整改项、提交（按所绑定版本的表单解释）
  activities.json  comments.json  evidence.json（文件元数据 + 挂载 + 作废记录）
  evidence/<evidence_id>/<清洗后文件名>
  report.html        # 人类可读报告：自包含 HTML，可打印为 PDF
  schemas/*.json     # 本格式的 JSON Schema（与仓库 schemas/export 同源）
```

- **授权**：需要 `view_case` + `export_case`；每个 Finding 再按 `view_finding` 逐个过滤（"批量读取不能放宽授权"，`docs/architecture.md:128`）。
- **一致性**：元数据在 `snapshot_read`（REPEATABLE READ）中读完即提交事务，之后流式读取对象，与证据下载相同，读对象期间不持有事务。ZIP 边输出边计算 sha256，与元数据核对。
- **上限**：超过 `EXPORT_DOSSIER_MAX_BYTES` 时返回 422，不截断。是否改为异步任务见 Q9。
- **报告结构**固定且通用：概要 → 底稿汇总 → 发现项与整改 → 证据清单 → 操作记录。**所有字段标签都取自场景文档和模板快照。**导出模板**不**做成元数据：让用户自定义模板，就要在数据库里存模板代码，有注入风险，也会把需求一步步推向报告设计器。
- **安全**：文本沿用公式注入防护（`docs/architecture.md:173`）；HTML 全部转义，不含脚本；写一条 INFO 日志 `case_dossier_export`；是否写平台审计事件见 Q9。

### 4.2 表格导入

| 对象 | 入口 | 语义 |
|---|---|---|
| 检查模板（XLSX/CSV） | 管理端上传，生成**模板草稿** | 列依次为：分组路径、项键、标题、指引、依据文本、采集类型、选项（`键:标签:结果类别`，多个用分号分隔）、单位、下限、上限、精度、必填、证据要求、允许不适用、默认处置、默认严重度 |
| 底稿离线填写（XLSX） | 从底稿导出（隐藏列含 `item_id`、`revision`），填写后回传 | 逐行校验，按 revision 做 CAS；值未变化的行跳过，因此重复导入是幂等的 |
| 用户与部门（CSV，管理员） | 管理设置 | 以 `login_name` 或部门路径为自然键；记录已存在则报错，不做 upsert |

- **两阶段导入**：
  - `?mode=validate`：只校验不写入，返回完整的逐行报告（`row`、`column`、`code`、`params`）。
  - `?mode=apply`：再做一次全量校验，**全部合法才在一个事务内写入，否则一行都不写**（Q5）。
- **防护**：限制文件大小和行数；openpyxl 使用 `read_only=True, data_only=True`，不计算公式；拒绝含宏的文件格式；限制压缩比，防止 zip bomb。
- **被否决**：部分提交。它会留下"只导入了一半"的底稿或模板，重试时还得判断哪些行已经写入。把逐行错误报告做好，让用户改完再整份重传，体验更好。

## 5. 前端（决策 D15、D16）

- **动态渲染**：`web/src/metadata/` 下实现 `SchemaForm` 和 `SchemaDescriptions`。
  - `SchemaForm` 按字段 profile 映射到 antd `Form.Item` 及对应控件（见 §1.3 的类型表）；`SchemaDescriptions` 用 `Descriptions`（`column={{ xs: 1, md: 2 }}`）展示。
  - 字段名使用嵌套路径（如 `['scenario_data', key]`）。服务端 422 返回的 `errors[]` 按字段落到对应的 `Form.Item` 上，并聚焦第一个错误（沿用 `docs/design.md:242`）；提示文案仍由 `ruleMessages.ts` 按错误码映射。
  - **遇到未知字段类型或未知格式版本时，字段只读显示为文本，并禁止提交**。这与"未知场景版本拒绝解释"的原则一致。
- **适配器演进**：
  - `ScenarioUiRegistry` 仍按精确的 `(key, version)` 解析；没有注册适配器的版本，用 `DeclarativeScenarioUi(document)` 构建。
  - 场景文档通过 `GET /api/v1/scenario-versions/{id}/definition` 获取。文档内容不可变，以 sha256 作强 ETag，可以永久缓存。
  - @1 场景在差分测试通过后切换到声明式适配器，以现有 real 浏览器测试（不改断言）作为视觉与交互回归。之后删除 `processReviewV1.tsx` 和 `complianceReviewV1.tsx`。
- **按钮由服务端给出**：页面按 `available_commands` 渲染按钮；`blocked_by` 在按钮旁显示为说明或禁用原因（如"需先指定整改负责人"）。按钮可见不代表一定能执行，最终以写入时服务端的结果为准。
- **授权呈现方式不变**：
  - 读取得到 403/404 时，用 `Result` 展示；
  - 写入得到 403 时，显示中性提示，并重新校验主资源；
  - 遇到 409 时先刷新，再由用户重新确认（`docs/design.md:231-247`）；新增的 409 码 `revision_conflict`、`already_derived` 各自给出对应提示。
- **新页面**：
  - 审查计划列表与详情：新增导航项"审查计划"，图标 `ScheduleOutlined`，需要同步修改 design.md。
  - Case 详情页新增"执行底稿"标签页。
  - 底稿填写页：宽屏左侧用 `Anchor` 按分组导航，窄屏改为顶部 `Select`；每个检查项一张 `Card`；测量项显示规格和自动判定的 `Tag`；选择"不适用"时必须填原因；证据就地上传。
  - 派生抽屉：预填 Finding 表单，可多选检查项合并派生。
  - 时间线：Activity 与评论合并展示，用 `Timeline`。
  - 个人设置：联系方式、通知偏好。
  - 管理设置：新增"检查模板"和"Webhook"。

  所有新页面按路由懒加载，入口包保持不变（`npm run check:entry`）。
- **视觉层**：
  - 结果类别的颜色**不能由元数据指定**，由内核映射到 design.md 中已实测达标的语义色：
    - `pass`：完成色 `--ant-green-8`；
    - `fail`：高严重度色 `--ant-volcano-8`（对比度 6.4:1），不借用逾期专用的红色；
    - `not_applicable` 和未填写：中性色；
    - `info`：进行中色 `--ant-blue-7`。
  - 处置标签用中性 Tag 加文字。
  - 指标卡片用 `Card` + `Statistic`，数值来自后端投影；完成度用 `Progress`，百分比由后端给出的计数换算，仅用于展示。
  - 颜色从不作为唯一的信息载体。
- **不做可视化设计器（D16）**：场景文档和模板以 JSON 或表格文件的形式编写，经 CLI 或管理 API 完成"校验 → 预览 → 发布"。后续的作者工具只做结构化编辑器、校验结果和示例运行结果，不做拖拽式设计器（`docs/architecture.md:303`）。
- **被否决**：前端继续按 lifecycle 枚举决定显示哪些按钮。原因有二：声明式场景下前端不可能预先知道迁移；按钮可见性会与服务端判断产生偏差。

## 6. 主数据扩展（决策 D13）

| 类别 | 方式 | 理由 |
|---|---|---|
| 联系方式（邮箱；日后可加 IM 账号） | **固定表** `user_contact_points` | 系统依赖它的语义（投递、验证、唯一性），需要类型和约束 |
| 通知偏好 | **固定表** | 同上 |
| 用于展示和筛选的扩展属性（工号、岗位、电话、部门编码等） | **元数据**：`attribute_schema_versions`（字段 profile，按组织和实体类型分版本），值存于 `users.attributes` / `departments.attributes` JSONB，按当前版本校验；可见性 `visibility: admin_only | org_visible` | 不同组织需要的字段不同，不应写死；直接复用字段 profile，不必再造一个校验器 |
| 多部门隶属、部门负责人 | **固定表** `department_memberships(user, department, role: member|manager)`，是否做取决于 Q8 | 这会影响授权和收件人展开，必须是内核语义，不能是自定义字段 |

- 扩展属性**不参与授权**，不做 ABAC，符合 ADR-0002"按关系授权"的原则。候选人搜索接口可以按 `org_visible` 的属性筛选。
- **被否决**：
  - ①全部做成固定字段：每个组织提出新需要都得改代码。
  - ②把联系方式放进自定义 JSONB：投递依赖的字段失去类型、约束和索引。
  - ③EAV 表：查询和校验都更复杂。
  - ④用扩展属性做授权：权限变得无法推导、无法测试。
