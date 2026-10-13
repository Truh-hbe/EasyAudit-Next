# 01 代码库现状与断层摸底报告

- 状态：提案（RFC），待维护者拍板；本文只记录现状与结论，不改变任何规则
- 基线：`origin/main` `5a2804b`（2026-10-13）
- 相关：[README](README.md) · [02 元模型](02-meta-model.md) · [03 扩展与协作](03-extension-and-collaboration.md) · [04 路线图](04-roadmap-and-dod.md)
- 证据约定：所有 `file:line` 都相对仓库根目录；调研期间仓库只读。OpenAPI 对比的方法是只读执行 `create_app().openapi()`，再与 `openapi/openapi.json` 求差集

## 1. 总体判断

- **内核扎实，原样保留**。依据：组织复合外键（`src/easyaudit_next/review_core/persistence/models.py:105-161`），锁内授权的统一入口（`src/easyaudit_next/review_core/application/authorization.py:151-198`），append-only 触发器（`alembic/versions/20260821_0005_m1_4_review_core_persistence.py:433-442`、`alembic/versions/20260826_0008_m2_4_rectification.py:74-106`），结构化错误码（`src/easyaudit_next/rules.py:19-105`）。
- **业务层只覆盖"登记发现项 → 整改 → 验证"**。缺执行底稿；证据只能挂在整改项上；场景差异要同时改前后端代码；协作只有站内信。
- **最大的结构性问题不在内核，而在场景差异的表达方式**。差异写在 Python 和 TSX 两份代码里，新增一个场景要改四处：后端 Policy、组合根注册、CLI 发布、前端适配器，并且要发两次版。
- **现有抽象已经为元数据化留好了接口**。`ScenarioPolicy` Protocol（`src/easyaudit_next/review_core/domain/scenario_registry.py:22-67`）把"状态集合"（内核枚举，`src/easyaudit_next/review_core/domain/models.py:85-147`）和"迁移、守卫、权限、校验"（场景）分开了。两个 v1 场景约九成重复（B3），差异只是数据。

## 2. 对既有事实的核实

| # | 事实 | 结论与补充 | 证据 |
|---|---|---|---|
| 1 | 计划 → 活动 1:N 后端支持，前端无计划列表/详情 | **属实**。后端已有 `GET /review-plans`（列表）和 `GET /review-plans/{plan_id}`（详情），前端 `listReviewPlans` 已封装，但没有任何页面调用它。追加活动的路由存在，但唯一入口是"新建计划"向导的第二步。没有接口能修改已有活动所属的计划。**计划没有授权模型**（见 B1） | 端点 `src/easyaudit_next/api/review_planning.py:246-278`；`plan_id` 入参 `src/easyaudit_next/api/review_contracts.py:42-49`；FK `src/easyaudit_next/review_core/persistence/models.py:110-114,147`；路由 `web/src/app/shell/ProductShell.tsx:103-123`；向导 `web/src/features/reviewPlans/wizardSteps.ts:1-5`、`web/src/features/reviewPlans/ReviewPlanCreatePage.tsx:133`；入口按钮 `web/src/features/reviewCases/ReviewCaseCollectionPage.tsx:115`；未用 API `web/src/api/product.ts:368-370`；设计约束 `docs/design.md:114` |
| 2 | 证据只指向 `action_items` | **属实**。领域模型写明"anchored to one ActionItem"。上传只有整改项一个入口。证据行不可修改 | `src/easyaudit_next/review_core/persistence/models.py:375-418`（FK `:379-384`）；`src/easyaudit_next/review_core/domain/models.py:187-201`；路由 `src/easyaudit_next/api/review_evidence_uploads.py:258`；登记 `src/easyaudit_next/review_core/application/review_rectification.py:682-762`；`docs/architecture.md:245`；触发器 `alembic/versions/20260826_0008_m2_4_rectification.py:74-90` |
| 3 | 没有检查表/底稿 | **属实**，全仓库检索不到相关概念。Finding 只有 title、description、severity、scenario_data | `src/easyaudit_next/review_core/persistence/models.py:222-233` |
| 4 | 整改提交只有一个 `comment` | **基本属实，需更正**：实际有三种固定形状，各带一个文本字段。计划提交用 `root_cause`，完成提交和驳回用 `comment`，另有保留键 `stage`/`result`。前端把这些键写死；API 接收任意 dict，没有表单引用 | `src/easyaudit_next/scenarios/process_review/v1.py:505-561`；`src/easyaudit_next/scenarios/compliance_review/v1.py:722-776`；`src/easyaudit_next/api/review_contracts.py:209-211`；`web/src/scenarios/findingCommandKit.tsx:130-155,195-201` |
| 5 | 无评论；通知只有站内信且不可变 | **属实**。除手动催办和自动提醒外，只有 4 类事件发通知：加入团队、成为参与方、成为执行人、提交验证。**签发、通过、驳回、重开和活动流转都不通知**，被驳回的整改负责人收不到任何提示。没有 SMTP/Webhook 配置；`backend` 网络是 internal，不能出网 | 种类 `src/easyaudit_next/notifications/models.py:18-26`；编排 `src/easyaudit_next/collaboration/notification_orchestration.py:63-128`；不可变触发器 `alembic/versions/20260827_0010_m3_2_notifications.py:150-190`；网络 `deploy/compose.yaml:3,215-216` |
| 6 | 用户只有 display_name、主部门、平台角色、启用状态 | **属实**。部门授权**只认主部门**，表达不了兼职或多部门 | `src/easyaudit_next/platform/persistence/models.py:89-97`；`src/easyaudit_next/review_core/application/authorization.py:68-75,132-141` |
| 7 | 场景以 Python 代码定义 | **属实**。`scenario_versions` 只是指向代码版本的发布指针，没有内容。Registry 进程全局，以 `(key, version)` 为键。前端另有一套代码适配器 | `src/easyaudit_next/review_core/persistence/models.py:51-71`；`src/easyaudit_next/review_core/domain/models.py:58-60`；`src/easyaudit_next/review_core/domain/scenario_registry.py:70-91`；`src/easyaudit_next/composition.py:57-67`；`web/src/scenarios/index.ts:10-12` |

## 3. 补充发现：后端耦合与缺陷

| 编号 | 发现 | 影响 | 证据 |
|---|---|---|---|
| B1 | 计划没有授权模型。`list_plans`、`get_plan` 只检查用户是否活跃；`create_case` 只检查计划是否存在；计划层只有 `create_review_plan` 一个权限 | 计划标题对全组织可见，任何人都能往别人的计划里加活动，"计划进度"也无从谈起 | `src/easyaudit_next/review_core/application/review_planning.py:144-153,175-179`；`src/easyaudit_next/review_core/domain/planning_policy.py:5-6` |
| B2 | 权限词表是事实上的内核契约，却以字符串字面量散落在 10 个模块里 | 元数据化需要一个单一来源，回答"文档能引用哪些权限"；现在改名无法静态发现遗漏 | `src/easyaudit_next/review_core/application/review_planning.py:60-62`、`review_findings.py:40-42`、`review_rectification.py:76-81`、`review_verification.py:56-58`、`review_closure_findings.py:35`；`src/easyaudit_next/workbench/query_service.py:47-49`；`src/easyaudit_next/management/query_service.py:50-52`；`src/easyaudit_next/notifications/subject_context.py:36-37`；`src/easyaudit_next/collaboration/nudge.py:36-38`、`notification_orchestration.py:47`；`src/easyaudit_next/review_case_queries/query_service.py:36` |
| B3 | 两个场景约九成重复：角色规格、Case 工作流、Action 工作流与操作、授权、提交策略几乎逐行一致。差异只有字段键、`finding_type`、`accept_observation`（授予 reviewer），以及观察项重开后回到 `open` | 差异本质是数据；照现在的写法，每增加一个场景就要再复制约 800 行 | 角色 `src/easyaudit_next/scenarios/process_review/v1.py:101-121` 对 `src/easyaudit_next/scenarios/compliance_review/v1.py:122-143`；Case 工作流 `process_review/v1.py:187-246` 对 `compliance_review/v1.py:222-283`；重开差异 `compliance_review/v1.py:343-357` |
| B4 | 应用服务按里程碑逐层继承：`ReviewPlanningService → ActionAware… → ClosureAware…`，`FindingLifecycleService → ActionAware… → ClosureAware…` | 再用子类叠加底稿、证据会让 MRO 失控；新模块应改用组合 | `src/easyaudit_next/review_core/application/review_rectification.py:88,113`；`review_verification.py:61`；`review_closure_findings.py:38` |
| B5 | 内核枚举不一致：执行人角色 `primary/collaborator` 被 DB CHECK 和领域枚举写死，而 Case 和 Finding 的角色是自由字符串、由场景校验 | 元数据化后整改项角色不可配置。短期可以保留，但要写进文档 | `src/easyaudit_next/review_core/persistence/models.py:344-347`；`src/easyaudit_next/review_core/domain/models.py:173-175`；对比 `models.py:178-180,261-264` |
| B6 | `SubmissionPurpose` 声明了 `finding_report`、`closure`，从未使用 | 这是包络余量，新增用途可以不改 CHECK | `src/easyaudit_next/review_core/persistence/models.py:443-446`；`src/easyaudit_next/review_core/domain/models.py:263-267` |
| B7 | Activity 的主体弧只有 Case、Finding、Action、Submission 四种；Notification 的主体弧只有三种 | 底稿、评论没有挂载点。扩弧需要迁移，ADR-0005 允许 | `src/easyaudit_next/review_core/persistence/models.py:493-496`；`src/easyaudit_next/notifications/persistence.py:65-68` |
| B8 | 发现项的"处置类型"藏在 `scenario_data.finding_type`（JSONB）里，只有场景代码能解释 | 管理视图、导出、工作台无法按处置统计，底稿派生也无法通用地选择默认处置 | `src/easyaudit_next/scenarios/compliance_review/v1.py:191-204,413-437`；读侧只有生命周期计数 `src/easyaudit_next/management/schemas.py:29-37` |
| B9 | 通知编排是命令式的，由 API 路由逐个调用 | 每新增一种事件都要改路由代码，没有可配置的规则表 | `src/easyaudit_next/api/review_planning.py:454-462`；`src/easyaudit_next/api/review_findings.py:199-207`；`src/easyaudit_next/api/review_rectification.py:238-246,321-329,379` |
| B10 | OpenAPI 基线只覆盖运行时 70 个操作中的 53 个；检查是单向的，只比对 operationId、tags、responses | 缺少验证提交、重开、通知、管理列表/进度、操作记录、催办等 17 个操作，新接口可能在没有契约的情况下漂移 | `scripts/check_openapi.py:17-24` |
| B11 | `/api/v1/meta/domain-model` 仍返回 `stage="M1.4"` | 残留接口，且带里程碑代号 | `src/easyaudit_next/api/router.py:86-97` |
| B12 | `EvidenceResponse` 向客户端暴露了 `storage_key` | 架构文档说知道它没有用处，但没有必要暴露 | `src/easyaudit_next/api/review_contracts.py:199`；`docs/architecture.md:263` |
| B13 | 整改项只有 title 和 due_at，没有说明、要求或场景字段 | design.md 的信息架构要求展示"完成要求"，但没有数据可展示 | `src/easyaudit_next/review_core/persistence/models.py:310-316`；`src/easyaudit_next/api/review_contracts.py:150-152`；`docs/design.md:109` |
| B14 | 场景显示名是代码里的英文（如 `"Process Review"`），目录接口原样返回 | 中文名只存在于前端术语表 | `src/easyaudit_next/scenarios/process_review/v1.py:604-609`；`src/easyaudit_next/review_case_queries/review_catalog.py:41-51` |
| B15 | Registry 进程全局、按 `(key, version)` 取，而场景目录按组织存储 | 场景文档一旦能按组织导入，不同组织的同名同版本内容可能不同，必须改为按 `scenario_version_id` 解析 | `src/easyaudit_next/review_core/domain/scenario_registry.py:87-91`；`src/easyaudit_next/review_core/persistence/models.py:27-34`；`src/easyaudit_next/review_core/application/review_planning.py:513-532` |

## 4. 前端断层

| 编号 | 断层 | 证据 |
|---|---|---|
| F1 | 没有计划列表和详情页，也无法向已有计划追加活动（见 §2 #1） | `web/src/app/shell/ProductShell.tsx:103-123` |
| F2 | 场景字段的标签、控件和组装逻辑写在 TSX 里，校验写在 Python 里，**同一组字段有两个事实来源** | `web/src/scenarios/processReviewV1.tsx:35-40,46-68,132-180` |
| F3 | 前端复刻了状态机：Case 命令按 lifecycle 枚举，发现项交互按 lifecycle 分支，整改项是否可写也由前端推导 | `web/src/scenarios/caseCommandKit.ts:68-85`；`web/src/scenarios/processReviewV1.tsx:113-131`；`web/src/scenarios/actionOperationsKit.ts:13-26` |
| F4 | 提交表单的键写死 | `web/src/scenarios/findingCommandKit.tsx:130-155,195-201` |
| F5 | 证据组件只服务整改项，上传协议只有 `uploadActionEvidence` | `web/src/features/actions/EvidenceSection.tsx:6,87`；`docs/design.md:255-259` |
| F6 | 没有底稿、评论、通知偏好、联系方式等页面 | `web/src/features/` 目录清单 |
| F7 | 前端按精确版本拒绝未知场景，这一点正确，应保留；问题是新场景必须改前端代码才能显示 | `web/src/scenarios/registry.ts:166-183`；`docs/architecture.md:208` |

## 5. 数据模型耦合缺陷汇总

| 缺陷 | 后果 | 处理（见 02/03） |
|---|---|---|
| `evidences.action_item_id` 是单目标 NOT NULL FK | 发现项、底稿项、评论都挂不了证据，同一文件也不能复用 | 文件与挂载分离（D8） |
| `action_items` 没有 `case_id` | 新的挂载类表无法用 FK 证明"同一个 Case" | 增列、回填，加复合 FK（D9） |
| 处置类型存在 JSONB 里 | 读侧和派生逻辑无法通用 | 新增 `findings.disposition_key` 列（D6） |
| `submissions.payload` 没有表单引用 | 历史提交只能靠前端代码解释 | 由文档定义表单，按 Case 绑定的版本解释 |
| `scenario_versions` 没有内容 | 场景只能写在代码里 | 新增 `scenario_version_documents` 表（D3） |
| 计划没有成员和生命周期 | 无法授权，也无法统计进度 | `plan_members` 加 `lifecycle`（D14） |
| 用户没有联系方式 | 无法外发通知 | 新增 `user_contact_points` 表（D13） |
| 通知种类是封闭枚举，中文文案写在后端 | 每加一种事件都要改代码 | 通知改为"类别 + 事件键"，由规则驱动（D11） |

## 6. 需修订的 ADR 与 architecture.md 条目（建议措辞，在后续 PR 中修改，本 PR 不动）

| # | 位置 | 现状 | 建议措辞 |
|---|---|---|---|
| A1 | 新增 ADR-0007《声明式场景定义与内核包络》；ADR-0003 状态改为"部分被 ADR-0007 取代" | `docs/adr/0003-scenario-extension.md:8,16-20`：只能注册代码 Policy；"M0 不引入万能低代码或数据库动态状态机" | ADR-0003 状态行追加："由代码注册 Policy 的方式已被 ADR-0007 取代：Policy 也可以是不可变的声明式场景文档，由随代码版本化的引擎解释。状态集合、迁移包络和内核强制守卫仍由内核代码定义，所以这不是数据库动态状态机。" |
| A2 | ADR-0001 后果第 1 条；`docs/architecture.md:303` | "不在 M0 引入微服务、事件总线或分布式事务"；"明确不做：…消息总线…" | ADR-0001 改为："不引入微服务、消息中间件或分布式事务。跨通道投递使用库内 outbox 表，由 Web 进程之外的定时任务分发（见 ADR-0009）。" architecture.md 中"消息总线"改为"消息中间件（库内 outbox 不在此列）" |
| A3 | `docs/architecture.md:303` | "通用表单构建器、运行时实体设计器、BPMN 或流程设计器" | 改为"可视化表单或流程设计器、运行时实体设计器、BPMN。在内核包络内、按字段 profile 编写的声明式场景文档与检查模板不在此列（见 ADR-0007）" |
| A4 | ADR-0005 后果第 2、4 条 | "可选类型化可空外键 + Check，或按目标建关联表"；"仅非关键辅助关系可…采用通用引用" | 追加一节"多目标关系的标准做法"，分两种情况。①**一行只指向一种目标、但目标有多种类型**的关系，例如证据挂载、评论：使用互斥弧，即类型化可空 FK + `num_nonnulls` CHECK + `target_kind` 一致性 CHECK；以 Case 本身为目标时，各弧列全为 NULL，由 `case_id` 指向目标。②**两类对象之间的多对多关系**，例如底稿项与发现项的关联：使用关联表，两端各有一条 FK。两种情况都通过 `(x_id, case_id, organization_id)` 复合 FK 指向父表，父表提供 `UNIQUE(id, case_id, organization_id)`。Generic FK 仍然禁止。" |
| A5 | 新增 ADR-0008《证据文件与挂载分离》 | `docs/domain.md:30` 写"挂在 ActionItem 上的不可变证据元数据" | domain.md 改为："Evidence 是 Case 内不可变的文件元数据；EvidenceAttachment 把文件挂到发现项、整改项、底稿项、评论或提交上；作废只能追加记录。" |
| A6 | 新增 ADR-0009《outbox 与外发通道》 | `docs/architecture.md:179-201` 只有站内通知和提醒 | 在"通知与提醒"一节追加："外部通道（邮件、Webhook）在业务事务中写入 `outbound_messages`，由 systemd timer 运行 `easyaudit-next dispatch-outbound` 分发；Web 进程不得 import 分发器（`check_architecture.py` 强制）。投递至少一次，以消息 id 去重。" |
| A7 | 新增 ADR-0010《执行底稿层》 | `docs/domain.md:150-154`"暂不建模" | domain.md 增加 Worksheet、WorksheetItem、结果类别、派生关联等概念与不变量（见 02 §4） |
| A8 | `docs/architecture.md:40-46,121` 锁顺序 | 没有 Plan、Worksheet、Comment | 全局锁序改为 `IdempotencyKey → Organization → ReviewPlan → ReviewCase → User → Worksheet → WorksheetItem → Finding → ActionItem → {Submission/Evidence/Attachment/Comment}`，并逐条列出新路径（见 02 §7） |
| A9 | `docs/architecture.md:245` | "`POST …/action-items/{id}/evidence-uploads` 是登记 Evidence 的**唯一**入口" | 改为"按目标划分的上传入口（Case 本身、整改项、发现项、底稿项、评论）共用同一条三段事务管线，这是登记 Evidence 的唯一方式" |
| A10 | `docs/architecture.md:158` | "本阶段 409 的 body 仍只有 `detail`" | 改为"409 可以携带 `code`（如 `worksheet_item.revision_conflict`、`worksheet_item.already_derived`），前端按码细分；没有码的 409 仍按通用冲突处理" |
| A11 | `docs/architecture.md:28-34` 架构检查清单 | 没有权限词表约束 | 追加："权限键只能在 `review_core/domain/permissions.py` 和场景文档中出现，`check_architecture.py` 禁止其他模块出现权限字面量" |
| A12 | ADR-0002 | 业务角色只存在于 Case/Finding/Action 关系中 | 只有在 Q1 选择引入组织级"模板管理"角色时才修订，否则不动 |
| A13 | `docs/design.md:80,114` | 一级导航只有四项；"当前没有独立的计划列表" | 新增一级导航"审查计划"（`ScheduleOutlined`），并补充底稿页、动态表单、结果类别配色规范（见 03 §5） |
| A14 | `docs/domain.md:48-55,126,136` | 场景机制写的是代码；`scenario_data` 字段列在文档里 | 场景机制改为引用 ADR-0007；具体字段以对应版本的场景文档为准，domain.md 不再罗列 |
| A15 | `docs/architecture.md`"事务与并发"或"部署"一节（新增条目） | 没有相关规则；现有 append-only 触发器会无条件拒绝 `UPDATE`，例如 `alembic/versions/20260826_0008_m2_4_rectification.py:74-90` | 新增"在 append-only 表上回填"："需要给 append-only 表新增可推导列并回填时，只允许在同一个迁移函数里按顺序执行：取得该表的 `ACCESS EXCLUSIVE`（通过 `ADD COLUMN` 或显式 `LOCK TABLE`）→ `DISABLE TRIGGER <名>` → 回填 → `ENABLE TRIGGER <名>`。不得使用 `DISABLE TRIGGER ALL` 或 `session_replication_role`。迁移测试必须断言回填后触发器已重新启用，且 `UPDATE`、`DELETE` 仍被拒绝。单元测试扫描 `alembic/versions/`，强制 DISABLE 与 ENABLE 成对出现，并且只能用于允许名单内的触发器。给按列清单判断不可变的表（如 `notifications`）新增列时，必须同时把新列加入不可变清单。" |

## 7. 必须保留、不得退化的资产

- Case 锁内授权（`lock_case_and_build_context`），以及"先取 Case 锁再授权"的写路径规则（`docs/architecture.md:119-125`）。
- 父行锁用 `FOR NO KEY UPDATE`（`docs/architecture.md:50-55`）。
- "数据库唯一约束是最终仲裁"（`docs/architecture.md:67-70,188-190`）。
- append-only 触发器。
- 通知不写标题快照（`docs/architecture.md:186`）。
- 读侧不持久化第二份真相（`docs/architecture.md:162`）。
- 证据三段事务、单桶按组织前缀的服务端 key（`src/easyaudit_next/review_core/application/evidence_storage.py:94`）、孤儿清理与完整性校验、备份恢复演练。
- 前端按精确版本拒绝未知场景。
- 结构化错误码"只增不改名"（`src/easyaudit_next/rules.py:7`）。
