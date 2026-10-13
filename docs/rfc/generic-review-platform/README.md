# 通用审查平台顶层设计 RFC

- 状态：提案（RFC），待维护者拍板。本目录只有设计文档；ADR、`docs/architecture.md`、`docs/domain.md`、`docs/design.md` 的修订另开 PR（见 [04 §6](04-roadmap-and-dod.md#6-后续文档-pr-清单本-rfc-不修改这些文件)）。
- 基线：`origin/main` `5a2804b`（2026-10-13）。
- 来源：难题委员会两份独立稿件（Claude Opus、Gemini），由总指挥裁决后以 Opus 稿为主线整理。分歧与裁决见文末。

## 定位

EasyAudit-Next 是面向跨部门协作的通用审查与合规管理平台。它提供抽象、可复用的审查闭环引擎，用来支撑不同部门、不同业务形态的审查、稽核、合规检查与任务跟进。设计与具体业务场景解耦，不为任何特定业务硬编码。

## 核心思路

- 现有的底层工程原样保留：复合外键、锁序、Case 锁内授权、append-only、幂等、结构化错误码。现在缺的是三层：**执行层**（底稿）、**元数据层**（场景配置化）、**外发层**（邮件与 Webhook）。
- 现有的 `ScenarioPolicy` Protocol 已经把"状态集合"（内核）和"迁移、守卫、权限、校验"（场景）分开了。只要有一个**随代码版本化的引擎**能解释不可变的场景文档，并实现同一个 Protocol，场景就能变成数据，内核状态机和应用服务都不用改。
- 元数据只能在内核规定的**包络**内选择，所用的守卫和字段类型都来自封闭集合。所以每份文档都能静态校验，错误码稳定，不变量 I7、I8、I9 也无法被绕过。

## 文档导航

| 文档 | 内容 |
|---|---|
| [01 代码库现状与断层摸底报告](01-current-state-and-gaps.md) | 对任务书 7 条事实的核实，后端补充发现 B1–B15，前端断层 F1–F7，数据模型耦合缺陷，ADR 与 architecture.md 待修订条目 A1–A15 及建议措辞 |
| [02 通用审查元模型与领域模型规范](02-meta-model.md) | 四层模型，ERD（定义层、执行层、证据与协作、投递），不变量，状态机（标注哪些沿用内核），租户隔离与外键策略，锁顺序扩展，权限词表，关键决策 D1–D4、D6–D9、D14 |
| [03 通用扩展与协作机制设计](03-extension-and-collaboration.md) | 场景文档格式，Schema 语言（D5），守卫库，发布与测试，affordances（D15），结构化整改与评论（D10），通知总线（D11），导入导出（D12），前端（D15、D16），主数据（D13） |
| [04 分阶段演化路线图与里程碑](04-roadmap-and-dod.md) | 依赖图，通用 DoD，P0–P8 各阶段的改动范围与 DoD，试点价值门槛，后续文档 PR，风险登记，开放问题 |

## 关键决策

| # | 决策（选择） | 被否决方案 | 详见 |
|---|---|---|---|
| D1 | **元数据边界**。内核持有：状态集合、迁移包络、内核强制守卫、权限词表、守卫库、字段类型库。场景文档只能在包络内选择并命名迁移，给守卫填参数，并定义角色到权限的映射、表单、处置、收件人和通知规则 | 通用表达式或可组合谓词 AST（不能静态分析，错误码不稳定，锁内要读的事实不可控）；在数据库里配置状态集合（违反红线 1） | [02 D1](02-meta-model.md#d1-元数据边界) |
| D2 | `DeclarativeScenarioPolicy(document)` 实现现有 Protocol，内核应用服务不改 | 重写应用服务、直接读元数据（约 3,000 行代码受影响，并发论证全部要重做） | [02 D2](02-meta-model.md#d2-引擎实现现有-protocol) |
| D3 | Case 通过 `scenario_version_id` 引用不可变文档（sha256 加触发器），不复制；发布流程为"草稿 → 校验 → examples → 发布 → 退役" | 每个 Case 复制一份文档；热修已发布的文档 | [02 D3](02-meta-model.md#d3-版本化发布与绑定) |
| D4 | @1 场景先写成文档，用差分测试证明与现有代码等价，再切换，下一次发版删除代码 Policy；历史数据一律不改写 | 长期双轨并行；把历史 Case 改绑到新版本 | [02 D4](02-meta-model.md#d4-现有场景与数据的无损迁移) |
| D5 | 采用 JSON Schema 受限 profile 加 UI Schema；Python 和 TS 各实现一个校验器，共用一套一致性语料 | 完整 JSON Schema + rjsf（正则方言不一致，与 design.md 冲突）；Pydantic 动态模型 | [03 §1.3](03-extension-and-collaboration.md#13-schema-语言json-schema-受限-profile--ui-schema决策-d5) |
| D6 | 新增 `findings.disposition_key`，每个处置映射到一条内核轨道（`rectify_and_verify` 或 `acknowledge`） | 新增 Finding 状态；继续存在 `scenario_data`；让处置自由定义可用动作 | [02 D6](02-meta-model.md#d6-处置类型) |
| D7 | 底稿：模板 → 不可变的模板版本 → Case 下的实例，按项复制快照；填写用 CAS，修订历史 append-only；完成度在读侧计算；派生走既有的 `create_finding` 加 M:N 关联，用唯一索引保证幂等 | 底稿项即 Finding；自动派生；每次填写写一条 Activity；持久化完成度计数 | [02 D7](02-meta-model.md#d7-底稿模型) |
| D8 | 证据的文件与挂载分离：用一张 `evidence_attachments`，以互斥弧挂到各目标（也可以直接挂到 Case 本身），并加 Case 复合 FK；作废以追加记录表示；存储仍为单桶、按组织前缀。`evidences.case_id` 的回填在迁移内按名暂停 append-only 触发器后执行，执行后断言触发器已恢复 | Generic FK；每种目标一张关联表；在 `evidences` 上直接加弧；原地更新作废列；按组织或业务域分桶 | [02 D8](02-meta-model.md#d8-多态证据) |
| D9 | `action_items` 和 `evidences` 增加 `case_id`，通过回填和复合 FK，在数据库层证明"同属一个 Case" | 用触发器校验（只能兜底） | [02 D9](02-meta-model.md#d9-给-action_items-与-evidences-增加-case_id) |
| D10 | 评论单独建 append-only 表，可挂到任意目标，不进 Activity、不改变状态；多角色复核作为 `verifying` 内的步骤 Submission | 评论写进 Activity；新增复核状态；富文本 | [03 §2](03-extension-and-collaboration.md#2-结构化整改与协作决策-d10) |
| D11 | 通知：Activity 作为领域事件；站内通知和 outbox 在同一事务内写入；外部 timer 运行 `dispatch-outbound`（`SKIP LOCKED` 租约、退避、死信可重新入队）；Webhook 用 HMAC 签名，密钥派生、不入库 | 消息中间件；在 Web 进程里起后台线程；按 Activity 游标轮询 | [03 §3](03-extension-and-collaboration.md#3-通知总线决策-d11) |
| D12 | 卷宗 ZIP（manifest、校验和、JSON、证据、HTML 报告）结构固定，标签取自元数据；导入先校验再应用，全有或全无 | 导出模板也做成元数据；导入部分提交 | [03 §4](03-extension-and-collaboration.md#4-导入导出决策-d12) |
| D13 | 联系方式和通知偏好用固定表；用于展示和筛选的扩展属性用字段 profile 定义、存 JSONB，不参与授权 | 全部做成固定字段；联系方式放进 JSONB；EAV；ABAC | [03 §6](03-extension-and-collaboration.md#6-主数据扩展决策-d13) |
| D14 | 计划：增加 `active/archived` 和 `plan_members`（内核固定的 owner/viewer 两种角色）；追加活动需要 `plan.manage`；进度在读侧计算 | 计划对全组织可见；计划沿用场景角色；四态生命周期 | [02 D14](02-meta-model.md#d14-计划作为一等公民) |
| D15 | 后端返回 `available_commands`（可执行命令及被阻塞的原因）；SchemaForm 基于 antd，遇到未知字段类型时 fail-closed | 前端按 lifecycle 枚举决定显示哪些按钮 | [03 §1.6](03-extension-and-collaboration.md#16-可执行命令清单affordances属于决策-d15)、[§5](03-extension-and-collaboration.md#5-前端决策-d15d16) |
| D16 | 不做可视化设计器；场景文档和模板以文件形式提交，经过"校验 → 预览 → 发布" | 拖拽式表单或流程设计器 | [03 §5](03-extension-and-collaboration.md#5-前端决策-d15d16) |

## 试点价值门槛

| 门槛 | 阶段 | 试点时用户能做什么 |
|---|---|---|
| **A：恢复试点** | P0 契约基线、P1 声明式引擎、P2 计划、P3 证据多态、P4 底稿层（建议 P5 的评论一并完成） | 在计划下成批安排审查活动；按模板执行底稿，逐项记录合格、不合格和实测值；就地附证据；一键派生发现项；完成整改、验证、关闭的闭环；查看计划进度 |
| **B：扩大到多部门** | A + P5 结构化整改与协作、P6 通知总线、P7 导入导出 | 结构化整改反馈和多步复核；邮件与 Webhook 触达；卷宗归档；底稿离线填写 |

上线检查仍按 [pilot-launch.md](../../operations/pilot-launch.md) 执行。

## 需要维护者拍板的问题

| # | 问题 | 推荐默认值 |
|---|---|---|
| Q1 | 场景文档和检查模板由谁编写、谁发布？是否跨组织共享？ | 只允许 `system_admin`；不跨组织共享，需要时通过文件导出、导入复用 |
| Q2 | 计划 owner 不是某个 Case 的成员时，能看到什么？ | 能看到 Case 摘要投影，看不到发现项标题和明细 |
| Q3 | 邮件和 Webhook 携带多少内容？ | 默认 `minimal`（类别、ID、链接）；`summary` 按端点单独开启，并写平台审计 |
| Q4 | 外发分发如何调度？ | 每分钟一次的 timer |
| Q5 | 导入出错时如何处理？ | 全有或全无，附逐行报告 |
| Q6 | 代码实现的 @1 何时退役？ | 差分测试通过后的下一次发版 |
| Q7 | 能否在 `open` 状态下修改处置类型？ | 允许，作为独立的 `reclassify` 命令，必须填原因，写 Activity |
| Q8 | 是否支持一人多部门、是否把部门负责人作为收件人？ | 门槛 A 不做 |
| Q9 | 卷宗导出同步还是异步？是否写平台审计？ | 同步流式，设大小上限；写平台审计 |
| Q10 | 是否同意按 01 §6 修订"明确不做"、ADR-0001、ADR-0003 的措辞？是否接受在迁移内暂停 append-only 触发器后回填（A15）？ | 都同意；如不接受 A15，改用只插入的归属表（02 D8 方案 B） |
| Q11 | 能否在 `scheduled` 状态下预填底稿？ | 由场景文档在包络内声明，默认不允许 |
| Q12 | 修订记录、评论、outbox 保留多久？ | 暂不清理，并入"数据保留"设计 |

## 委员会分歧与裁决

两位委员独立完成了同一份任务书。Gemini 稿与 Opus 稿有 6 处分歧，总指挥全部裁决采用 Opus 方案。

| # | 议题 | Gemini 方案 | 裁决 | 否决 Gemini 方案的原因 |
|---|---|---|---|---|
| 1 | 元数据边界 | 声明式规格包，含 JSON Schema（含 `pattern`）、受限谓词 AST、角色权限矩阵；处置类型自由声明 `allowed_actions`；"审查配置热发布" | 封闭包络 + 封闭守卫库，由 `DeclarativeScenarioPolicy` 实现现有 Protocol（D1–D3） | 没有包络时，文档能启用内核不保证不变量的迁移，违反红线 1；谓词可以组合，所需事实和违规码就无法静态确定，锁内加载可能遗漏；热发布绕过了"草稿 → 校验 → examples → 发布"流程；`pattern` 在前后端的正则方言不一致 |
| 2 | @1 迁移 | 第 4 阶段才"反向编译"为元数据包，此前保留 Python Policy 作兜底，双轨并行 | 先写成文档，用差分测试证明等价，再切换，下一次发版退役代码 Policy（D4） | 双轨期间两套实现会分叉；底稿、提交表单、导入都依赖字段 profile 和守卫库，引擎必须先行；满足维护者"废除代码级硬编码场景"的要求 |
| 3 | 多态证据 | 正文主张"按目标类型的强类型挂载关联表"，并否决单表互斥弧（理由是"无法一证多挂"）；DDL 中的挂载表只有 `(x_id, organization_id)` 外键，`voided_at` 可原地更新 | 单一 `evidence_attachments`，用互斥弧加 Case 复合 FK；作废以追加记录表示（D8、D9） | 一证多挂靠"文件与挂载分离"解决，与是否用互斥弧无关；每种目标一张表就要 N 套授权和查询；没有 Case 复合 FK，就无法在数据库层证明文件与目标属于同一 Case；原地更新作废列破坏 append-only |
| 4 | 处置类型 | 场景声明 `finding_types`，各自列出可用动作和守卫；观察项的确认用 `has_case_role` 守卫控制 | `findings.disposition_key` 映射到内核轨道（D6） | 轨道与包络子图绑定，能保证处置定义完整（签发、关闭、重开各走哪条边）；授权与守卫保持分离，角色判断不混进守卫 |
| 5 | 计划 | 四态生命周期 `draft/active/completed/archived`，加看板 | `active/archived` + `plan_members`，进度在读侧计算（D14） | `completed` 可以从各 Case 的状态推导出来，持久化它就是第二份真相（`docs/architecture.md:162`）；`draft` 与 `active` 行为没有区别；四个状态会带来更多需要保持一致的迁移和守卫 |
| 6 | 底稿并发锁 | Case 只加 `FOR KEY SHARE` 的"共享意向锁"，底稿项加行锁，填写之间互不阻塞；完成度计数异步刷新 | 在 Case 锁（`FOR NO KEY UPDATE`）上串行，配合短事务、批量保存和压测（02 §7） | PostgreSQL 的 `FOR KEY SHARE` 与 `FOR NO KEY UPDATE` 不冲突，成员移除和用户停用会在填写的授权与写入之间提交，"锁内授权"的保证（`docs/architecture.md:119-123`）因此失效；PostgreSQL 行锁也没有意向锁语义；把完成度计数落库违反读侧规则 |

**从 Gemini 稿吸收、经核实的内容**

- 后端已有计划的列表与详情端点（`src/easyaudit_next/api/review_planning.py:246-278`），只是前端没有使用；也没有修改已有 Case 所属计划的接口。已写入 01 §2。
- Webhook 死信支持人工重新入队：先提供 CLI `retry-outbound`，管理界面后续再做。已写入 03 §3。
- 证据存储继续使用单桶、按组织分前缀（`src/easyaudit_next/review_core/application/evidence_storage.py:94`），挂载关系不改变存储键。已写入 02 D8。
- 前后端校验一致性语料（两稿结论一致）；挂载底稿快照时用多值 INSERT 批量写入（02 §7、04 R9）；外发请求默认 10 秒超时；卷宗附 `checksums.sha256`，可直接用 `sha256sum -c` 校验。

**未采纳（与代码不符）**

- 上传路由的行号：实际在 `src/easyaudit_next/api/review_evidence_uploads.py:258`。
- `register_evidence` 的路径：实际在 `src/easyaudit_next/review_core/application/review_rectification.py:682-762`。

**未采纳（设计取舍）**

- 把联系方式作为 `users` 的固定列：改用 `user_contact_points` 表，以支持验证状态和后续增加的通道。
- 评论支持富文本：XSS 风险面更大，导出也更复杂。
- 整改表单示例中使用特定方法论的字段名：违反"不写死任何方法论"的约束。

## 红线自检

- **红线 1**：`review_cases`、`findings`、`action_items` 的状态集合、包络、CAS 和锁内授权管线都没有变化。新能力以挂载模块（worksheets、comments、outbound）和引擎（实现现有 Protocol）的形式进入。对内核表只做增列：`findings.disposition_key`、`action_items.case_id`、`action_items.scenario_data`、`activities.worksheet_id`、`evidences.case_id`。
- **红线 2**：示例只用中性键名。@1 中已有的取值（如 `finding_type` 的两个枚举值、`root_cause`）只作为现有代码事实被引用，不进入任何新的内核概念。
- **红线 3**：文档中没有内网地址、主机名、账号、客户名称或真实业务数据。
