# 架构

EasyAudit-Next 是一个模块化单体：一个 FastAPI 进程、一个 PostgreSQL 数据库、一个 React 前端。领域概念见 [domain.md](domain.md)，历史决策见 [adr/](adr/)。

本文只记录**必须遵守的规则**。改动需要打破其中一条时，在 PR 里说明原因并同步修改本文。

## 技术栈

- 后端：Python 3.12、FastAPI、SQLAlchemy 2 同步 `Session`、psycopg 3、PostgreSQL 17、Alembic。
- 前端：React + react-router、Vite、TypeScript、Vitest、Playwright、oxlint。
- 认证：本地账号 + Argon2id；服务端 Session，浏览器只持有 `__Host-easyaudit_session`（Secure、HttpOnly、SameSite=Strict）Cookie。

## 模块与依赖方向

```text
src/easyaudit_next/
  platform/                组织、部门、用户、认证、平台管理、平台审计
  review_core/             领域（纯 Python）→ 应用服务 → 持久化
  scenarios/               process_review、compliance_review 的版本化 Policy
  application/             跨 Platform 与 Review Core 的协调器（如最后管理者保护）
  collaboration/           通知编排、手动催办、自动提醒
  notifications/           Notification 持久化与收件箱
  workbench/  management/  review_case_queries/  review_resource_queries/   读侧查询
  api/                     HTTP 适配
  composition.py           唯一组合根
```

`scripts/check_architecture.py` 在 CI 中强制：

- `platform/domain`、`review_core/domain`、`scenarios` 不依赖 FastAPI、Pydantic、SQLAlchemy、Alembic、API、基础设施或应用层。
- 只有 `scenarios` 自身和 `composition.py` 可以 import `scenarios`。
- `review_core` 不 import `collaboration`、`management`、`notifications`、`workbench`。
- 通用收件人编排中不出现 `submit_rectification` 等场景权限字面量。

## 事务与并发

- 一个请求一个事务：实体变更、Activity、Notification 在同一个事务内提交或回滚。
- 单行状态变更使用 CAS：`UPDATE ... WHERE id = :id AND lifecycle = :expected`。无匹配行时返回 409，且不写 Activity。
- 跨行不变量使用父行 `SELECT ... FOR UPDATE`，固定加锁顺序，**禁止反向加锁**：
  - 整改（Action 增改、指派、证据、整改提交）：`Finding → Action / Assignee / Evidence / Submission`
  - 验证、重开、Case 关闭：`ReviewCase → Finding → Submission / Activity`
  - Case 成员增删、用户停用：`Organization → Case（按 ID 排序）→ User（按 ID 排序）`
- 等待锁之后的决定性读取必须刷新 ORM 状态（`populate_existing=True`），不能使用锁前的 identity map 快照。
- 锁后发现生命周期已变化，按并发冲突（409）处理，而不是按业务校验失败（422）处理。
- 每个并发修复都要有 PostgreSQL 双 Session 竞争测试（`tests/integration/*race*`、`*concurrency*`）。

## 授权

- 授权完全由 Case 固定的精确 Scenario 版本判断（`ScenarioPolicy.authorization.allows`），不能写成 `role_key == "lead"`，也不能给 `system_admin` 业务捷径。
- **上下文按目标构造。** Finding 只使用父 Case 的授权、自身的授权以及其下 Action 的授权；Action 只使用父 Case、父 Finding 和自身的授权。兄弟资源的授权不能扩大当前目标的权限。
- **批量读取只是查询优化，不能放宽授权范围。** 先批量取出事实，在内存中按目标分组，再逐个目标判断。
- 分页、计数、total 都基于已授权的结果集计算，不能先分页后过滤。
- 先检查可见性，再读取和返回决定性业务事实，避免通过校验错误泄露状态。
- 查询一律同时带上 `organization_id` 与实体 ID；知道一个 UUID 并不代表有权访问。

## API 错误语义

| 状态码 | 含义 |
|---|---|
| 403 | 已认证，但缺少所需的业务关系 |
| 404 | 组织范围内查不到，或未授权且不应暴露对象是否存在 |
| 422 | 请求、Scenario 数据、工作流或业务规则校验失败 |
| 409 | 过期的生命周期、并发冲突、唯一性冲突 |

`openapi/openapi.json` 是稳定接口的基线，由 `scripts/check_openapi.py` 校验。

## 读侧

- Workbench（`/me/workbench`）和 Management（`/management/review-cases`）只做查询投影，不持久化 WorkItem、进度快照之类的第二份真相。
- 截止日期规则：
  - Case 逾期：`planned_end_at < as_of`，且状态为 `scheduled` / `in_progress`。
  - Action 逾期：`due_at < as_of`，且状态为 `todo` / `in_progress`。
  - 即将到期窗口为 7 天，只用于展示。
- 查询次数按资源类别固定，不随数据量线性增长；有测试比较 5 条与 100 条数据时的 SQL 次数。
- 管理范围：用户需要是 Case 的直接成员，并在该 Case 上持有 `manage_case_members` 与 `view_case`。子 Finding 仍需逐个检查 `view_finding`。

## 通知与提醒

- Notification 是投递记录，不是业务真相。阅读只改变 `read_at`，也不授予访问对象的权限。
- 事件通知的 `origin_activity_id` 必须来自本次变更在内存中返回的 Activity ID。禁止事后反查，包括按"最新一条"、按主题加类型、按时间戳。
- 去重由数据库唯一约束保证，禁止"先查后插"：
  - 事件通知：`组织 + 收件人 + origin_activity + kind`
  - 自动提醒：`组织 + 收件人 + kind + 主题 + 提醒发生键`。发生键绑定到当时的截止日期值。
- 手动催办（Finding / Action）是人的操作：写一条 Activity，再按收件人扇出 Notification。收件人为空时拒绝；发起人不会收到自己的催办。
- 自动提醒不写 Review Activity，只写 Notification。`collaboration/reminder_sweep.py` 与调度器无关，调度由外部触发。
- 收件人由 Scenario 的收件人语义在当时解析，部门展开到当时的活跃成员；历史通知的收件人不会被改写。

## 前端边界

- 权限、生命周期、截止日期、收件人、进度都以后端为准。前端只负责展示，按钮可见不代表有权操作。
- 前后端同源：`/api/v1/*` 与 SPA 同源，没有 CORS，没有浏览器可读的 token。
- 所有请求走 `web/src/api/client.ts`，不散落 `fetch()`。
- 场景相关的 UI 通过适配器按精确的 `(scenario_key, scenario_version)` 解析。版本未知时拒绝显示，不回退到其他版本。
- 409 表示数据已过期：刷新后让用户重试。禁止自动重放写请求，包括结果未知的创建请求。
- 不在本地长期保存业务状态的影子副本，写操作成功后刷新相关查询。

## 明确不做

微服务、分布式事务、消息总线、以 Redis 作为业务真相、通用分布式锁、BPMN 或流程设计器、通用表单构建器、运行时实体设计器、自定义仪表盘、匿名责任令牌、督办实体、原生移动端、由 AI 生成业务真相。
