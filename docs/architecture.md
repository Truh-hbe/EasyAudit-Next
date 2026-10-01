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
- 对象存储 SDK（`boto3`、`botocore` 等）只能在 `infrastructure/` 里 import；`infrastructure.object_storage` 适配器只由 `composition.py` 接线。业务代码依赖应用层的 `EvidenceObjectStore` 端口。

## 事务与并发

- 一个请求一个事务：实体变更、Activity、Notification 在同一个事务内提交或回滚。唯一的例外是 Evidence 上传（见"证据文件上传"）：流式写对象期间不允许持有任何事务，所以它是"预授权事务 → 写对象 → 登记事务"三段。
- 单行状态变更使用 CAS：`UPDATE ... WHERE id = :id AND lifecycle = :expected`。无匹配行时返回 409，且不写 Activity。
- 跨行不变量使用父行 `SELECT ... FOR UPDATE`，固定加锁顺序，**禁止反向加锁**：
  - 创建幂等：`IdempotencyKey → Organization → …`。带 `Idempotency-Key` 的创建请求在事务**第一条语句**抢占幂等键，之后才进入下面任何一条锁顺序（见"创建幂等"）。
  - 整改（Action 增改、指派、证据、整改提交）：`Finding → Action / Assignee / Evidence / Submission`
  - 验证、重开、Case 关闭：`ReviewCase → Finding → Submission / Activity`
  - Case 成员增删、用户停用：`Organization → Case（按 ID 排序）→ User（按 ID 排序）`
- 等待锁之后的决定性读取必须刷新 ORM 状态（`populate_existing=True`），不能使用锁前的 identity map 快照。
- 锁后发现生命周期已变化，按并发冲突（409）处理，而不是按业务校验失败（422）处理。
  - 自动提醒 sweep（每个候选一个事务）：`Organization(FOR KEY SHARE) → Case 或 Action → 收件人 User(KEY SHARE，由 Notification FK 隐式获得)`，与上面的顺序一致，见"通知与提醒"。
- 每个并发修复都要有 PostgreSQL 双 Session 竞争测试（`tests/integration/*race*`、`*concurrency*`）。

## 创建幂等

只覆盖 `POST /review-plans` 和 `POST /review-cases`，不是通用幂等框架。

- 客户端用可选请求头 `Idempotency-Key`（1–128 个可打印非空白 ASCII 字符（0x21–0x7E，不含空格），非法为 422）。不带头时行为与以前完全一样。
- 表 `create_idempotency_records`，主键即唯一作用域 `(organization_id, actor_user_id, operation, idempotency_key)`。存 `request_fingerprint`（sha256）、`response_status`，结果资源用两个类型化可空 FK `review_plan_id` / `review_case_id`（组织感知的复合 FK，不用 Generic FK，见 ADR-0005），CHECK 要求恰好填一个且与 `operation` 一致。
- **数据库唯一约束是最终仲裁，禁止"先 SELECT 再 INSERT"。** 创建事务的第一条语句是 `INSERT ... ON CONFLICT DO NOTHING RETURNING`：
  - 抢到：用**预先生成**的资源 id 正常创建（同一事务写入资源与 Activity），提交。记录一开始就是完整的，所以不需要回填，CHECK 恒成立。
  - 没抢到：PostgreSQL 的唯一索引插入会等待持有该键的事务结束。对方提交 → 读出记录：指纹相同则返回第一次创建的资源（201 + `Idempotent-Replayed: true`，不写 Activity，不产生任何副作用），指纹不同则 409（`Idempotency-Key reused with a different request`）；对方回滚 → 本事务的插入成功，正常创建。
  - 创建失败（422、授权失败、异常）整个事务回滚，键不会被占用。
- 重放按**当前**读取授权返回资源的当前表示（不存响应快照）；actor 已无权读取时按现有读取规则返回 403/404。
- 指纹：校验后的请求体 `model_dump`，键排序、datetime 统一为 UTC ISO、无空白，再取 sha256；`operation` 不计入（已在作用域里）。Plan：`title`、`planned_start_at`、`planned_end_at`；Case：`plan_id`、`scenario_key`、`scenario_version`、`title`、`planned_start_at`、`planned_end_at`、`scenario_data`。
- **该表所有外键都是 `DEFERRABLE INITIALLY DEFERRED`。** 立即检查的 FK 会在 claim 时对 Organization / User 行加 `FOR KEY SHARE`，两个并发创建各持一份后都要升级为 `FOR UPDATE`（`_lock_actor`），互相等待而死锁。延迟到提交时检查，此时本事务已持有 `FOR UPDATE`。`test_concurrent_creations_with_different_keys_do_not_deadlock` 固定了这一点。
- 不用 advisory lock：它需要自己的键空间与生命周期，而唯一索引已经给出等同语义，并且随事务回滚自动释放。
- **保留期**：试点期不清理幂等记录（规模很小）；并入"数据保留"一起设计。记录有 FK 指向资源与用户，清理前需要先确定这些行的删除规则。

## 数据库预算

业务 engine（`create_database_engine`）的连接池和服务端超时都显式配置（`platform/settings.py`，模板见 `.env.example`）：

| 配置 | 默认 | 作用 |
|---|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 10 / 5 | 每个 worker 进程最多 15 条连接 |
| `DB_POOL_TIMEOUT_SECONDS` | 10 | 等池超时；超时是 500（池耗尽说明预算或泄漏有问题） |
| `DB_POOL_RECYCLE_SECONDS` | 1800 | 连接最长存活 |
| `DB_CONNECT_TIMEOUT_SECONDS` | 5 | libpq 建连上限 |
| `DB_TCP_USER_TIMEOUT_MS` | 15000 | 已建立的连接上，已发送数据多久得不到 ACK 就报错 |
| `DB_KEEPALIVES_IDLE/INTERVAL_SECONDS`、`DB_KEEPALIVES_COUNT` | 10 / 5 / 3 | TCP keepalive：静默连接约 25 秒内判死 |
| `DB_STATEMENT_TIMEOUT_MS` | 15000 | 单条语句上限 |
| `DB_LOCK_TIMEOUT_MS` | 5000 | 等行锁/表锁上限（低于 statement_timeout，锁等待先于语句超时暴露） |
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` | 30000 | 事务里空闲超过此值，服务端终止连接 |

- **客户端上限**：业务 engine 给 libpq 下发 `connect_timeout`（建连上限）、`keepalives*` 和 `tcp_user_timeout`（发现已建立连接上的死对端）。keepalive 与 `tcp_user_timeout` 是否生效取决于平台是否支持对应的 socket 选项，见 libpq 文档；**TCP 存活检测不等于查询响应截止时间**：连接已建立、对端存活但不返回结果时，业务请求没有客户端截止时间，只依赖服务端的 `statement_timeout`（同步驱动加线程池模型，试点期接受；`ready` 探针有独立的客户端截止时间，会把这种情况暴露为 not ready）。URL 里已有的同名参数优先于 Settings，这是运维的显式选择：在 URL 里覆盖它们等于放弃 Settings 的默认上限，`connect_timeout=0` 表示无限等待。`DB_POOL_SIZE + DB_MAX_OVERFLOW` 至少为 2（Settings 校验）。
- 三个超时通过业务 engine 的连接参数 `options=-c ...` 下发，与 URL 里已有的 `options` **合并**（追加在后，同名以我们为准）。只作用于业务 engine：`alembic/env.py` 自建 NullPool engine，迁移不受 statement_timeout 限制；CLI（含 `run-reminder-sweep`）自建同样配置的业务 engine，同样受限；sweep 逐个候选取一条连接，任何时刻只占一条。
- **连接预算公式**：`workers × (pool_size + max_overflow) + readiness 探针 + 运维工具 < max_connections`。当前 compose：1 个 uvicorn worker × 15 + readiness 探针 1（single-flight，同一时间最多一条）+ 运维工具（`migrate`、备份 `pg_dump`、CLI，各按 1 条，预留 5）≈ 21，远低于 PostgreSQL 默认 `max_connections=100`（另有 superuser 预留 3）。增加 worker 或调大池之前先按公式核对。
- **超时的 HTTP 语义**：`statement_timeout`、`lock_timeout` 到期（SQLSTATE 57014 / 55P03）映射为 **503 + `Retry-After: 1`**，body 只有 `detail` 与 `request_id`，由 `RequestContextMiddleware` 统一处理并记 WARNING `database_timeout`。不用 409：409 的含义是"数据已过期，刷新后重试"，而超时并没有发现生命周期变化，只是暂时拿不到资源；前端对 409 会刷新数据，对 503 才是正确的"稍后重试同一个请求"。死锁（40P01）与 idle-in-transaction 终止不在此列，仍是 500（说明代码违反了加锁顺序或持有了空闲事务）。
- **没有运行时自检**：这些 timeout 由集成测试保证（`tests/integration/test_db_budget.py`：真实 PostgreSQL 上 `SHOW` 三个值等于配置、`options` 与 URL 合并、statement/lock 超时行为、idle-in-transaction 终止、迁移连接不受影响），不在启动时再向数据库查询比对，也不影响 `ready`。

## Session 活动时间

- `auth_sessions.last_seen_at` 最多每 `SESSION_TOUCH_INTERVAL_SECONDS`（默认 300）写一次。`AuthenticationService.touch` 在已加载的快照显示间隔内已写过时不发任何 SQL；UPDATE 自带 `last_seen_at IS NULL OR last_seen_at < touched_at - interval`，过期快照不会把时间往回写，也不会在已撤销/已过期的 Session 上写入。
- `last_seen_at` 只是运维信息，精度就是这个间隔；它不参与授权，`expires_at` 才决定 Session 是否可用。
- **试点期不删除 `auth_sessions` 行。** 它们是 `platform_audit_events.target_session_id`（复合 FK，`RESTRICT`）的锚点，每次登录成功都有一条审计引用，所以不改审计就删不掉；过期的 Session 由 `expires_at` 保证不可用（`authenticate` 检查）。表只增不删，试点规模下可接受；何时保留、何时删除，与审计 FK 一起在"数据保留"里设计。`cleanup-auth` 只清 `login_throttle`，并在输出里给出已过期 Session 的计数（不含 ID），不修改任何 Session。

## 登录限流

- 计数存在 PostgreSQL 表 `login_throttle(scope, key_hash, window_start, attempt_count, updated_at)`，主键 `(scope, key_hash, window_start)`。**限流计数属于运维记录，不是业务真相**：丢了只会放宽限制，不影响任何业务事实，也不进备份语义；表里只有 `sha256(规范化 login_name)` 与 `sha256(client ip)`，没有明文。
- 不用 Redis 或进程内存：进程内存在多 worker 之间不一致（限额被放大为 N 倍），重启后清零（攻击者可借重启重置）；Redis 是为这一项新增的外部依赖，而 PostgreSQL 已经是唯一的持久层，并且计数可以和失败审计在同一个事务里提交。
- **先计数后校验**：`AuthenticationService.login` 在任何凭证查询和 Argon2 之前，用单条 `INSERT ... ON CONFLICT DO UPDATE SET attempt_count = attempt_count + 1 RETURNING` 给两个维度各加 1：规范化后的 `login_name`（与 `login()` 的 normalize 一致，账号存不存在都计数）和 `request.client.host`（uvicorn 只信任网关的代理头，所以是真实客户端 IP）。任一维度 `> 上限` 就抛 `LoginThrottledError`，不做 Argon2。**计数在独立的短事务里执行并立即提交**（独立 Session，不与请求事务共用），行锁只在那两条 upsert 期间持有，所以 Argon2 期间不会阻塞同 IP 的其他登录；单条 upsert 原子，同一 key 并发得到互不相同的计数，进入密码校验的次数不超过上限。固定加锁顺序：先 `login_name` 后 `ip`。计数发生在请求 Session 拿到连接之**前**（路由到 `login` 之前没有任何查询），所以一次登录任何时刻最多占一条连接。登录成功清零 `login_name` 计数在**请求事务里**执行：此时 Argon2 已结束，从清零到提交只剩写 session 和审计，行锁持有很短，也不需要第二条连接。失败审计同样在请求事务里提交。
- **固定窗口的边界效应**：窗口是固定的，攻击者在一个窗口的最后 N 次加下一个窗口的最前 N 次，短时间内最多能得到 2N 次尝试（`login_name` 默认 10 次、IP 默认 100 次）。这是固定窗口相对滑动窗口的已知取舍，试点期接受；测试 `test_fixed_window_boundary_…` 固定了这一行为。
- 默认：固定窗口 15 分钟（按 epoch 对齐，边界只由时间决定），`login_name` 5 次，IP 50 次（`LOGIN_THROTTLE_*`）。登录成功清零该 `login_name` 当前窗口的计数；**IP 计数不动**——若成功时回减，攻击者可用自己的有效账号 1:1 抵消对他人账号的猜测。
- **429 与账号无关**：固定 body `{"detail": "Too many login attempts"}`，`Retry-After` 为当前窗口剩余秒数；401 的三种情况（账号不存在、密码错、停用）保持同一个响应。429 分支返回前，计数已经独立提交。被限流的尝试不写审计（避免攻击者灌满审计表），只写 WARNING `login_throttled`，字段只有 `throttle_scope`，不含 key 或 key_hash。
- 清理：`easyaudit-next cleanup-auth` 删除早于当前窗口的行（见 `deploy/` 下的 systemd timer）。
- **运维逃生口**：限流可被用来封锁已知登录名（对某名发超限请求即可，试点期私网内接受此风险）。`easyaudit-next cleanup-auth --clear-login-name <name>` 按规范化后的名字算 hash，删除它所有窗口的计数，立即解封。

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
| 409 | 过期的生命周期、并发冲突、唯一性冲突；创建时 `Idempotency-Key` 被不同请求复用 |
| 413 | Evidence 超过 `EVIDENCE_MAX_BYTES`（只用于上传） |
| 415 | Evidence 的类型不在白名单，或扩展名与声明的类型不一致（只用于上传） |
| 429 | 登录尝试过多（只用于 `login`，响应与账号无关） |
| 503 | 数据库 `statement_timeout` / `lock_timeout` 到期，带 `Retry-After`；对象存储不可用或未配置（上传，不带 `Retry-After`） |

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
- 自动提醒不写 Review Activity，只写 Notification。`collaboration/reminder_sweep.py` 与调度器无关：时钟、`occurrence_key` 和事务粒度都由调用方提供。
- **调度在 Web 进程之外。** systemd timer 每天 09:00（`Asia/Shanghai`）运行 `easyaudit-next run-reminder-sweep`（一次性容器，示例见 `deploy/easyaudit-reminder-sweep.*`）。`api/`、各模块的 `api.py`、`main.py`、`serve.py` 不得 import sweep、`scheduler_runs`、CLI 或任何调度库，`scripts/check_architecture.py` 强制（`tests/unit/test_web_process_has_no_scheduler.py`）。uvicorn 多 worker 或重启都不会导致重复或遗漏调度。
- **发生键**：默认 `occurrence_key = daily:<as_of 在 REMINDER_TIMEZONE（默认 Asia/Shanghai）下的日期>`，所以同一天内任意次运行（timer 补跑、手动重跑）共享同一个键；`--as-of`、`--occurrence-key` 可显式覆盖，用于补发或测试。
- **每个候选一个事务。** sweep 自己不持有长事务：发现候选（keyset 分页，按 id 升序，每页一个只读短事务，页间不丢位置；READ COMMITTED 下评估器会重新校验是否仍然逾期）和评估每个候选各用独立事务。单个候选失败（含 40P01、55P03）只回滚这一个候选，计入 `failed_count`，sweep 继续处理后面的候选。
- **锁序论证**：一个候选事务先 `SELECT … FOR KEY SHARE` 该 Organization 行，再对 Case（或 Action）`FOR UPDATE`，再插入 Notification，此时 Notification FK 对收件人 `users` 行和 `organizations` 行加 `KEY SHARE`（后者已持有）。这与 Web 的 `Organization → Case → User` 同序，而且事务内从不跨候选累积锁，因此不会与 Web 成员操作成环。第一版（单事务扫完所有候选）会在 `Case₁ → User → Case₂ …` 处与 Web 成环；"先锁 Organization"这一步是实测补上的：Notification 对 `organizations` 的 FK 检查本身是一次后置的 `KEY SHARE`，与 Web 持有的 `Organization FOR UPDATE` 冲突。`tests/integration/test_reminder_sweep_race.py` 固定了无死锁的时序，并保留旧的单事务形态作为必然死锁的反例。
- **运行记录 `scheduler_runs`**（`job_key`、`occurrence_key`、`as_of`、`started_at`、`finished_at`、`status`、各计数、`error_summary`）是**运维记录，不是业务真相，也不进 Review Core**。三段事务：(a) 短事务插入 `running` 并提交；(b) sweep 的各个候选事务；(c) 短事务写终态和计数。全部候选成功为 `succeeded`；只要有候选失败，或 sweep 整体无法运行，就是 `failed`（不设 `partial`：监控只需要区分"需要人处理"和"不需要"，细节在 `failed_count` 与 `error_summary`），CLI 以退出码 1 结束。进程崩溃会让记录停在 `running`，不做任何自动处理（不引入 `abandoned`）。
- **去重不依赖运行记录。** 禁止用"已有 `succeeded` 记录"跳过一次运行或代替业务去重；重跑总是完整执行 sweep，已提交的候选被 Notification 唯一索引去重（`created_count = 0`，`deduped_count` 等于上次的 `created_count`），失败的候选补上。计数来自 `INSERT … ON CONFLICT DO NOTHING RETURNING` 的实际返回行数，仍由数据库约束裁决，不是先查后插。
- `error_summary` 只含异常类名（加 SQLSTATE）和失败数，如 `failed_candidates=2: OperationalError/40P01 x2`；绝不写 `str(exc)`（SQLAlchemy 异常带 SQL 和参数）。CLI 在 stdout 输出一行 JSON（run_id、job_key、occurrence_key、计数、status），不经过请求日志的字段白名单。
- **新鲜度监控**：`easyaudit-next scheduler-status [--job automatic_reminder_sweep] [--max-age-hours 26]` 输出最近一次运行和最近一次成功的 JSON；最近一次 `failed`、最近一次成功早于 max-age、或从未运行，退出码为 1。最近一次仍是 `running`（进行中或已崩溃）本身不算失败，新鲜度只看最近一次成功。
- 收件人由 Scenario 的收件人语义在当时解析，部门展开到当时的活跃成员；历史通知的收件人不会被改写。

## 前端边界

- 权限、生命周期、截止日期、收件人、进度都以后端为准。前端只负责展示，按钮可见不代表有权操作。
- 前后端同源：`/api/v1/*` 与 SPA 同源，没有 CORS，没有浏览器可读的 token。
- 所有请求走 `web/src/api/client.ts`，不散落 `fetch()`。
- 场景相关的 UI 通过适配器按精确的 `(scenario_key, scenario_version)` 解析。版本未知时拒绝显示，不回退到其他版本。
- 409 表示数据已过期：刷新后让用户重试。禁止自动重放写请求，包括结果未知的创建请求。创建页在表单生命周期内持有一个 `Idempotency-Key`，用户手动重试、双击和网络失败后重新提交复用同一个键；键被不同请求复用（409）时提示刷新，不自动重放。
- 不在本地长期保存业务状态的影子副本，写操作成功后刷新相关查询。

## 部署

配置在 `deploy/`，规则由 `tests/unit/test_deploy_compose.py` 和 `deploy/smoke.sh` 强制：

- 只有 HTTPS 网关对外，且只发布 443。数据库、API、对象存储只在网络内部可达；`backend` 网络是 `internal`。
- 数据库迁移必须显式执行（`migrate` 服务），API 启动时不迁移。
- 所有容器非 root 运行；镜像固定到具体版本，不使用 `latest`。
- 密钥只通过未提交的文件（Docker secrets / `*_FILE`）注入，不写进 compose 或镜像。API 用 `s3_access_key_id`、`s3_secret_access_key`（Garage 导入的同一对）访问对象存储。
- API 只信任网关的代理头，不使用 `--forwarded-allow-ips='*'`。
- 自建镜像的 tag 是 `EASYAUDIT_RELEASE`（git commit SHA，必须设置，没有默认值），并带 OCI label `org.opencontainers.image.revision`。不使用 `latest`、`local`。

### 备份与恢复

工具在 `deploy/backup/`，操作见 [deploy/README.md](../deploy/README.md)。规则：

- 备份先 `pg_dump`，再经 S3 协议镜像对象（不打包 Garage 内部卷）。对象必须由服务端生成 key、只写一次、不覆盖（Pilot-4 遵守）；因此 dump 之后拷贝的对象集合一定是 DB 引用集合的超集，多出来的是孤儿，由孤儿清理处理。备份时 DB 引用的对象缺失，或 size/sha256 不一致，备份照常保留并在 manifest 标记 `integrity: degraded`，脚本以退出码 3 结束（不产出就丢了当前 DB，RPO 失守）；`verify` 对 degraded 判失败，`restore` 允许但先打印问题清单。
- 一个备份包 = `database.dump` + `objects/` + `manifest.json`，manifest 记录 release SHA（取自运行中镜像的 label）、alembic revision、各文件 sha256 和镜像 tag，保证同一 release、同一时间点。
- 保留策略：按天数清理，但最近一份 `integrity: ok` 的备份永远保留，degraded 备份不能把它挤出保留窗口。备份每 12 小时一次，`check-freshness.sh` 监控"最近一份 ok 备份不超过 24h"；调度本身不保证 RPO。
- 恢复只写入空目标（DB 无表、bucket 为空），不提供覆盖开关；`database`、`objects`、`environment` 三个入口在写入之前都要求 manifest 的 release 等于检出的 HEAD 和 `EASYAUDIT_RELEASE`（以及已有 api 容器的镜像 label），整环境恢复在写入之前先确认 DB 和 bucket 都为空，且 `alembic current` 等于 manifest revision 和该 release 的 head。
- 备份/恢复工具是接入 `backend` 网络的一次性容器（非 root、`cap_drop: ALL`、不发布端口），不在长驻容器里写文件，也不给 postgres 发布端口。
- secrets 和 TLS 证书不进备份包；和数据同盘的备份不算备份，异地拷贝由运维负责。
- 恢复演练（`deploy/backup/drill.sh`，CI job `backup-restore-drill`）是备份恢复的验收；演练通过网关 API 上传真实文件（含一个超过 part 大小的多段上传）来生成 Evidence，并从 bucket 读回对象核对 sha256；Pilot-4B 上线下载端点后，必须把"通过 API 下载 Evidence"加进演练。

## 证据文件上传

Evidence 元数据（`evidences` 表、`register_evidence`）早已存在；文件字节走对象存储。`POST /api/v1/action-items/{id}/evidence-uploads` 是登记 Evidence 的**唯一**入口，旧的 JSON 登记接口已删除（storage key、sha256、size 都由客户端提供，不可信）。

- **端口与适配器**：应用层的 `EvidenceObjectStore`（`put_stream` / `delete` / `exists`，`review_core/application/evidence_storage.py`）；S3 适配器在 `infrastructure/object_storage.py`（boto3）。适配器把 SDK 异常换成不带 endpoint、bucket、凭证的 `ObjectStoreError`；凭证只从 `OBJECT_STORAGE_*_FILE` 指向的文件读取，只存在于 botocore 客户端里。botocore 显式配置 `connect_timeout`、`read_timeout`（单次 socket 操作的空闲上限，不是总截止时间）、`retries`（standard，`total_max_attempts = OBJECT_STORAGE_MAX_ATTEMPTS`，含首次请求；botocore 的 `max_attempts` 只算重试次数，不能用；part 是内存里的 bytes，重试安全）、path-style 寻址，并设 `proxies={}`（内部端点不走环境里的 HTTP(S)_PROXY）；校验和只在 API 要求时计算（`when_required`），因为我们自己对流计算 sha256，各 S3 兼容实现对 SDK 默认的尾部校验和支持不一。同步 SDK 的每次调用都在 `asyncio.to_thread` 里，不阻塞事件循环。
- **请求体就是文件字节**，不用 multipart：Starlette 的 multipart 会先把整个 body 落到临时文件，handler 才开始，大小限制来得太晚，且可以填满磁盘。`Content-Type` 是文件类型，`X-Evidence-Filename` 是 percent-encoded UTF-8 的原始文件名，`description` 是 query 参数。**文件名只是元数据**：去掉路径成分、控制字符和双向控制符，限制 255 字符，永远不参与存储 key。
- **三段事务**（`api/review_evidence_uploads.py`）：
  1. 认证后在短事务里**预授权**（`authorize_evidence_registration`：与 `register_evidence` 相同的权限与 Action 校验，不加锁），随即 `commit()` + `expunge_all()`。此后到响应前，这个请求不持有任何事务，也不占着池里的连接——否则大文件上传会被 `idle_in_transaction_session_timeout`（30s）杀掉连接。`tests/integration/test_evidence_upload_api.py` 在对象存储的 `put_stream` 里查 `pg_stat_activity` 断言这一点（含真实 Cookie 认证链路）。
  2. 流式写对象：`request.stream()` 逐块读取，边读边算 SHA-256 和大小，满 8 MiB 就作为一个 part 上传（小于一个 part 的文件用单次 `PutObject`）。内存上限是约一个 part 加一个输入块，与文件大小无关；不先读进内存，也不先落盘。key 由服务端生成：`org/{organization_id}/evidence/{uuid4}`，只写一次，不覆盖（备份一致性模型的前提）。
  3. 新的短事务调用 `register_evidence`，传入**服务端计算的** key、size、sha256。它重新取用户（上传期间可能已被停用）、重新授权、按 `Finding → Action` 加锁、写元数据和 Activity，然后提交。
- **对象只在登记确定回滚时才删除**：登记在工作线程里跑，线程无法停止，请求被取消不等于登记没发生。所以登记线程**自己持有 Session**（线程内创建、提交或回滚、关闭，不碰请求作用域的 Session），`_register_and_settle` 用 task 包住它：已提交 → 保留对象；确定回滚 → 删除；**`COMMIT` 报错一律视为结果未知 → 保留对象**（之后的 `rollback` 只是尽力清理，它自己报错也只记日志，不能改变这个结论），记 `evidence_registration_outcome_unknown`。请求被取消后等待登记结果的时间**有上限**：`DB_STATEMENT_TIMEOUT_MS + DB_LOCK_TIMEOUT_MS + 5s`；超时同样按结果未知处理——保留对象，记 `evidence_registration_unsettled`（只有 `storage_key`），重新抛出取消，线程留在后台自己跑完。永远不会出现"有元数据、没对象"，最坏是没有元数据的孤儿对象，交给 4B。后台线程的寿命受"数据库黑洞下业务请求没有客户端截止时间"这一已接受风险（见"数据库预算"）约束，不另加机制。
- **失败清理**：写对象失败或中途超限，适配器 abort multipart，什么都不留；第 3 段失败（授权变化 403/404、生命周期变化 409/422、DB 错误），**尽力删除**刚写的对象，再返回原来的错误。删除也失败时对象成为孤儿，记 WARNING `evidence_object_orphaned`，字段只有 `storage_key`（日志白名单为此新增了 `storage_key`；key 里没有文件名和用户输入），留给 Pilot-4B 的孤儿清理。进程崩溃遗留的未完成 multipart 同样由 4B 处理。
- **限制**：`EVIDENCE_MAX_BYTES`（默认 25 MiB）。`Content-Length` 超限在读 body 之前就 413；没有 `Content-Length`（chunked）时累计到超限立即中止并 413。网关 Caddy 对 `/api/v1/*` 设 `request_body max_size`（26 MiB，略大于应用上限，纵深防御：它在上游读取 body 时才生效，所以不替代应用自己的 `Content-Length` 检查；改应用上限时同步改 `deploy/Caddyfile`，`tests/unit/test_deploy_compose.py` 检查两者关系，`smoke.sh` 用登录接口验证它真的生效）。类型白名单 `EVIDENCE_ALLOWED_CONTENT_TYPES`（默认 pdf、png、jpeg、docx、xlsx、pptx、txt、csv；只能是代码里有扩展名映射的类型，启动时校验）；不在白名单或扩展名与类型不一致 → 415；文件名为空或编码非法、空文件 → 422。
- **提前拒绝的代价**：413/415/422/403 在读 body 之前就返回，客户端可能还在发送，此时连接会被关闭，浏览器看到的可能是网络错误而不是状态码；前端对此有专门提示，且不自动重试。
- 对象存储不可用或未配置：上传 503（`object_storage_operation_failed` WARNING，字段只有 `component`、`reason`），不写元数据。

## 可观测性

- **Health 不对外。** `/health/live`、`/health/ready` 挂在根路径，不在 `/api/v1` 下；网关只转发 `/api/v1/*`，所以外部访问不到（`deploy/smoke.sh` 断言）。旧的 `/health` 已删除。
- `live` 只表示进程能响应，不访问数据库或任何外部依赖。`ready` 检查四项，全部通过才 200，否则 503：数据库 `SELECT 1`（连接和语句超时各 2 秒，用独立、不池化的 engine）、Alembic 当前 revision 等于镜像内脚本的 head、必需配置存在。响应体只有各项的 `ok`/`fail`，不带 DSN、revision、错误消息；细节写日志。
- `ready` 另有第四项 `object_storage`，**只检查可达性**：用 asyncio 原生连接（https 用 TLS）向 endpoint 发一个不签名的 `HEAD /{bucket}`，读到合法的 HTTP 状态行即 ok，403/404 也算（匿名请求本来就得不到 200）；连接失败、握手失败、非 HTTP 响应、超过截止时间都是 fail，`OBJECT_STORAGE_*` 缺失同样是 fail。它与数据库探针并发，共用同一个 2 秒截止时间，**不用线程池**：线程无法取消，botocore 的 `connect_timeout`/`read_timeout` 又只是单次 socket 操作的空闲上限，不是总截止时间——对端一点点吐字节就能让线程一直活着，拖住事件循环关闭和进程退出（测试用静默、逐字节吐、RST 三种对端，断言包含 `asyncio.run` 退出在内的总耗时）。DNS 解析（`getaddrinfo` 不可中断）在探针自己的 **daemon 线程**里做，结果经 `call_soon_threadsafe` 回传，超时就丢弃，所以既不占默认 executor、也不阻塞解释器退出；随后按解析出的地址连接，TLS 的 SNI 和证书校验仍用原主机名。`OBJECT_STORAGE_ENDPOINT` 在 `Settings` 里限定为 `http(s)://host[:port]`（不带路径、查询、凭证），探针与 S3 客户端因此对 endpoint 的理解一致；IPv6 的 Host 头带方括号。超时或取消时 socket 立即关闭，`wait_closed` 另有 0.25 秒上限；没有全局状态。**取舍：凭证和 bucket 是否正确不在 `ready` 里校验**（密钥错了、桶不存在会在第一次上传时以 503 暴露），响应只有 `ok`/`fail`，细节写 WARNING 日志（只有异常类型和 `file:line`，不含 endpoint、bucket、凭证）。
- `ready` 的数据库探针是全 async 的（psycopg `AsyncConnection`，不走业务连接池、不占线程池），连接、查询、关闭共用一个 2 秒（`READINESS_TIMEOUT_SECONDS`）的客户端截止时间，超时后立即关闭 socket 并返回 503。探针连接参数由与业务 engine 相同的 SQLAlchemy dialect 转换（`libpq_connect_kwargs`），`sslmode`、`sslrootcert`、Unix socket、已有 `options` 原样保留（`options` 追加 statement_timeout 而不是覆盖），所以不会在业务要求 TLS 时明文探测。整个评估另有兜底总预算（超时 + 1 秒）；评估被取消同样立即关闭 socket。期望的 alembic head 只在 lifespan 启动时用 `asyncio.to_thread` 读一次，存进 `app.state`（不用模块级全局状态，多个 app 实例互不影响）；读取失败会写 ERROR 日志，该进程在重启之前 `ready` 一直报 migrations fail，`live` 不受影响。镜像里的脚本读不出来说明镜像本身坏了，应由运维重启或回滚，应用不自愈，也绝不在事件循环里同步读文件。并发探针采用 single-flight（in-flight 任务存在 `app.state`）：已有探针在跑时，后来者等待同一次结果，不再另开连接。`/health/live` 也是 `async def`。
- **request_id 由服务端生成**（UUID4），通过 `X-Request-ID` 响应头返回；忽略客户端传来的同名请求头。未处理异常的 500 响应体带 `request_id`。
- 日志是 stdout 上一行一个 JSON，只用标准库（`infrastructure/observability.py`），级别由 `LOG_LEVEL` 控制（默认 INFO）。uvicorn 通过 `python -m easyaudit_next.serve` 启动，使用同一个 formatter，自带 access log 关闭。
- 每个请求结束写一条 access 日志：`timestamp`（UTC）、`level`、`request_id`、`method`、`route`（路由模板，匹配不到为 `null`，不含 query string）、`status_code`、`latency_ms`、`organization_id`、`actor_user_id`（在认证依赖里写入，未认证为 `null`）。
- 探针（`/health/live`、`/health/ready`）返回 2xx 时 access 日志级别为 DEBUG，默认 INFO 下不输出；非 2xx（如 ready 的 503）照常 INFO，ready 失败的细节仍以 WARNING 记录。
- "必需配置"的定义：`DATABASE_URL` 非空且可解析；`APP_ENV` 不是 `development` 时，`DATABASE_URL` 不能等于内置的开发默认值（说明密钥没有注入）。
- formatter 对 `extra["fields"]` 做键白名单（`ALLOWED_FIELDS`），白名单外的键被丢弃并只在 `dropped_fields` 里报告键名；值限制类型和长度。异常细节只能来自 `describe_exception` 产出的 `ExceptionDetails`。静态规则按方法名（不按接收者名字）检查所有 `debug/info/warning/error/exception/critical/log` 调用：消息（位置参数或 `msg=`）必须是常量字符串，不得插值，不得有 `**` 展开，`extra` 只能是字面量字典且每个键都是 `fields`/`exception_details` 字符串常量。
- 日志消息必须是常量事件名（`tests/unit/test_logging_conventions.py` 强制），变量数据放 `extra={"fields": ...}`，不用 `%s` 参数或 f-string，因为 formatter 会原样输出 message。我们不提供 WebSocket，`uvicorn.run(ws="none")`；uvicorn/第三方 logger 最低 INFO（即使 `LOG_LEVEL=DEBUG`），避免协议层 DEBUG 日志回显原始请求。响应已开始后才失败（后台任务、流式响应）时，access 日志保留已发送的状态码并置 `error: true`，异常另记一条。
- **禁止记录**：密码、Cookie、session token/id、Authorization、secret、请求体、Evidence 内容；任何请求头和请求体都不写日志。
- 异常只记录 `exception_type` 和 `file:line:function` 堆栈，**不记录 `str(exc)`**（SQLAlchemy 异常的 message 带 SQL 和参数）。`ExceptionDetails` 里没有 message 字段，任何异常类型（包括领域异常）都不记录 message。
- `observability`、`readiness` 只能被 `api/`、`main.py`、`serve.py` 使用，Review Core 与 Platform 不依赖它们（`scripts/check_architecture.py` 强制）。

## 明确不做

微服务、分布式事务、消息总线、以 Redis 作为业务真相、通用分布式锁、BPMN 或流程设计器、通用表单构建器、运行时实体设计器、自定义仪表盘、匿名责任令牌、督办实体、原生移动端、由 AI 生成业务真相。
