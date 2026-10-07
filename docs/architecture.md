# 架构

EasyAudit-Next 是一个模块化单体：一个 FastAPI 进程、一个 PostgreSQL 数据库、一个 React 前端。领域概念见 [domain.md](domain.md)，历史决策见 [adr/](adr/)。

本文只记录**必须遵守的规则**。改动需要打破其中一条时，在 PR 里说明原因并同步修改本文。

## 技术栈

- 后端：Python 3.12、FastAPI、SQLAlchemy 2 同步 `Session`、psycopg 3、PostgreSQL 17、Alembic。
- 前端：React + react-router、Ant Design 6 + @ant-design/icons、Vite、TypeScript、Vitest、Playwright、oxlint。UI 规范见 [design.md](design.md)。
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

- 一个请求一个事务：实体变更、Activity、Notification 在同一个事务内提交或回滚。唯一的例外是 Evidence 上传（见"证据文件上传"）：流式写对象期间不允许持有任何事务，所以它是"预授权事务 → 写对象 → 登记事务"三段。Evidence 下载同理：短只读事务授权后立即结束，流式读取期间不持有事务。
- 单行状态变更使用 CAS：`UPDATE ... WHERE id = :id AND lifecycle = :expected`。无匹配行时返回 409，且不写 Activity。
- 跨行不变量使用父行 `SELECT ... FOR NO KEY UPDATE`，固定加锁顺序，**禁止反向加锁**（见下方“父行锁强度”）：
  - 创建幂等：`IdempotencyKey → Organization → …`。带 `Idempotency-Key` 的创建请求在事务**第一条语句**抢占幂等键，之后才进入下面任何一条锁顺序（见"创建幂等"）。
  - 整改（Action 增改、指派、证据、整改提交）：`ReviewCase → Finding → Action / Assignee / Evidence / Submission`（Case 锁用于锁内授权，见“授权”）
  - Finding 创建、参与人、直接流转、手动催办：先取 `ReviewCase`（催办此后只写 Activity / Notification）；Finding 的参与人与流转随后用 CAS 串行化
  - 验证、重开、Case 关闭：`ReviewCase → Finding → Submission / Activity`
  - Case 成员增删、用户停用：`Organization → Case（按 ID 排序）→ User（按 ID 排序）`
  - 部门父节点变更：`IdentityOrganizationService.move_department` 自己先取 `Organization`（`FOR NO KEY UPDATE`），再用 `DepartmentRepository.get_current`（`populate_existing`，绕过 identity map 的旧快照；生产 Session 是 `autoflush=False`，所以只在锁后的决定性读取里用，普通 `get` 不刷新）重读被移动的部门、校验父部门并遍历祖先，最后 UPDATE。锁在服务层而不是 API 入口，所以任何调用 `move_department` 的代码（目前只有管理 API）自动获得保护。**约束：已经持有 Case、User 等其他行锁之后，不得再调用 `move_department`**，否则 `Organization` 会排到它们后面，锁顺序反向。成环抛 `DepartmentCycleError`，API 返回 409。同组织的部门结构变更串行，跨组织互不影响。`tests/integration/test_department_move_race.py` 固定双 Session 竞争，以及“锁后刷新”的确定性顺序用例。数据库触发器 `reject_department_cycle` 只是兜底（读事务快照，拦不住写偏差；对已损坏的环会无限递归，修改需要迁移，另行处理）。
- **父行锁强度**：被外键引用的父行（Organization、User、Case、Finding、Action）一律用 `FOR NO KEY UPDATE`，SQLAlchemy 写作 `.with_for_update(key_share=True)`。
  - 原因：子表 INSERT 会对被引用的父行加 `FOR KEY SHARE`，它与 `FOR UPDATE` 冲突、与 `FOR NO KEY UPDATE` 不冲突。用 `FOR UPDATE` 时，一个请求先 INSERT 了引用 User/Case 的行（持有 KEY SHARE），再 INSERT Notification（需要 Organization 的 KEY SHARE），就会和持有 Organization `FOR UPDATE`、正在等该 User/Case 的成员管理/停用请求形成隐式的反向加锁，PostgreSQL 报 40P01，Web 请求返回 500。`NO KEY UPDATE` 之间、与 `FOR UPDATE` 仍然互斥，所以显式的 `lock_*` 互斥语义不变。
  - 只有事务里会修改该行主键或被引用唯一键时才允许 `FOR UPDATE`。目前没有这种情况；叶子行（`local_credentials`，没有 FK 引用它）可以保留 `FOR UPDATE`，在 `scripts/check_architecture.py` 里白名单。
  - 只读的共享前置锁用 `FOR KEY SHARE`（`read=True, key_share=True`），例如自动提醒 sweep 对 Organization 的预锁。
  - SQLAlchemy 陷阱：`with_for_update()` 是 `FOR UPDATE`；`key_share=True` 生成的是 `FOR NO KEY UPDATE`；`FOR KEY SHARE` 要写 `read=True, key_share=True`。
  - `check_architecture.py` 只放行带 `key_share=True` 的写法，禁止无参的 `with_for_update()`（`FOR UPDATE`）和只有 `read=True` 的写法（`FOR SHARE`，与 `NO KEY UPDATE` 冲突）；`test_parent_lock_fk_race.py` 固定了 Case / User 两条边的双 Session 竞争，并断言各父行锁编译出的 SQL。
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
- **该表所有外键都是 `DEFERRABLE INITIALLY DEFERRED`。** 立即检查的 FK 会在 claim 时对 Organization / User 行加 `FOR KEY SHARE`，两个并发创建各持一份后都要升级为行锁（`_lock_actor`），互相等待而死锁。延迟到提交时检查，此时本事务已持有行锁。（父行锁改为 `FOR NO KEY UPDATE` 后，升级本身不再与 `KEY SHARE` 冲突，延迟检查对这一点已不是必需，但保留无害。）`test_concurrent_creations_with_different_keys_do_not_deadlock` 固定了这一点。
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
- **授权在锁内、基于锁后读取的数据判断。** Case 角色（`CaseMember`）在 Case 锁下被撤销，所以任何写路径都必须先取 Case 锁（`FOR NO KEY UPDATE`），再用锁后读到的成员关系重建 `AuthorizationContext` 并决定；锁前的上下文不能守护写入。统一入口是 `lock_case_and_build_context`（`review_core/application/authorization.py`）。
  - 锁前可以保留一次便宜的拒绝（404/403 语义不变），这样未授权用户不会排队抢锁；通过后取锁，锁内**重复同一条**权限检查，并使用锁后的 Case（生命周期同样以锁后为准）。
  - 全局锁序是 `Organization → Case → User → Finding → Action / Submission`：需要 Organization 锁的路径（成员增删、用户停用、`move_department`）先取 Organization，且持有 Case/User 锁后不得再取；整改、参与人、催办等路径过去不取 Case 锁，现在**新增**了 Case 锁，且排在 Finding 之前，与验证路径一致，没有反向加锁。锁内重读 actor 时按 `Case → User` 取 User 行锁，与成员增删/停用的顺序相同。
  - 新增写路径时，先取 Case 锁再授权；测试用双 Session：A 持 Case 锁撤销角色，B 在锁前通过检查并等待，A 提交后 B 必须被拒绝（`test_post_lock_authorization_race.py`）。
  - 锁内顺序固定（`lock_case_and_build_context`）：Case 锁 → 重新读取 actor（停用在 Case 锁下提交，所以拿到锁后能看到；已停用则拒绝）→ **先**比较 Case 生命周期（变化即 409，不是 422）→ 重建授权上下文 → 授权。生命周期比较必须在授权之前：授权闭包会用锁后的 Case 做业务校验，Case 已被推进时校验会抛 `ValueError`（422），而这应当是并发冲突。锁前的拒绝必须和锁内是**同一个** `authorize` 函数，包括由业务决策得到的 `required_permission`，只读用户因此不会排队抢 Case 锁。
  - **用户 PATCH 同理：锁后重读、只改请求显式给出的字段。** `PlatformAdministrationService.update_user` 先取 Organization 锁，再 `lock_users_for_update`（`FOR NO KEY UPDATE` + `populate_existing`）锁住 actor 与目标，之后的最后管理者检查、会话撤销、审计 metadata 和返回值全部基于锁后的行；调用方传入的 actor 快照只用于锁前的便宜拒绝，授权（`system_admin` 且启用）以锁后的 actor 为准。停用路径的 Organization → Case → User 顺序不变，`update_user` 在其内部重复取同一批锁是无等待的。测试：`test_user_update_race.py`。
  - 不在此规则内：`primary_department_id`（`update_user` 改部门时不取 Case 锁，仍有残留窗口，部门授权只影响 Finding/Action 级部门授权），以及 Finding/Action 级授权本身（目前没有删除这些授权的写路径）。
- **上下文按目标构造。** Finding 只使用父 Case 的授权、自身的授权以及其下 Action 的授权；Action 只使用父 Case、父 Finding 和自身的授权。兄弟资源的授权不能扩大当前目标的权限。
- **批量读取只是查询优化，不能放宽授权范围。** 先批量取出事实，在内存中按目标分组，再逐个目标判断。
- 分页、计数、total 都基于已授权的结果集计算，不能先分页后过滤。
- 先检查可见性，再读取和返回决定性业务事实，避免通过校验错误泄露状态。
- 查询一律同时带上 `organization_id` 与实体 ID；知道一个 UUID 并不代表有权访问。

## API 错误语义

| 状态码 | 含义 |
|---|---|
| 403 | 已认证，但缺少所需的业务关系 |
| 404 | 组织范围内查不到，或未授权且不应暴露对象是否存在（Evidence 下载：不存在、跨组织、无读权限都是同一个 404） |
| 422 | 请求、Scenario 数据、工作流或业务规则校验失败；管理导出的行数超过 `EXPORT_MAX_ROWS` |
| 409 | 过期的生命周期、并发冲突、唯一性冲突；创建时 `Idempotency-Key` 被不同请求复用 |
| 413 | Evidence 超过 `EVIDENCE_MAX_BYTES`（只用于上传） |
| 415 | Evidence 的类型不在白名单，或扩展名与声明的类型不一致（只用于上传） |
| 429 | 登录尝试过多（只用于 `login`，响应与账号无关） |
| 500 | 未处理异常；Evidence 下载时元数据存在而对象缺失（数据丢失，见"Evidence 下载"） |
| 503 | 数据库 `statement_timeout` / `lock_timeout` 到期，带 `Retry-After`；对象存储不可用或未配置（上传与下载，不带 `Retry-After`） |

`openapi/openapi.json` 是稳定接口的基线，由 `scripts/check_openapi.py` 校验。

## 读侧

- Workbench（`/me/workbench`）和 Management（`/management/review-cases`）只做查询投影，不持久化 WorkItem、进度快照之类的第二份真相。
- 截止日期规则：
  - Case 逾期：`planned_end_at < as_of`，且状态为 `scheduled` / `in_progress`。
  - Action 逾期：`due_at < as_of`，且状态为 `todo` / `in_progress`。
  - 即将到期窗口为 7 天，只用于展示。
- 查询次数按资源类别固定，不随数据量线性增长；有测试比较 5 条与 100 条数据时的 SQL 次数。
- **一致快照**：管理视图的多条加载查询在 `snapshot_read`（`REPEATABLE READ, READ ONLY`）事务里执行。READ COMMITTED 下每条语句各取一份快照，并发提交会让计数和生命周期来自不同时刻。隔离级别必须在事务第一条语句之前设置，而请求事务已经做过认证查询，所以 `snapshot_read` 先提交（只读，无副作用），提交会把连接还回池，随后重新取一条连接开新事务（不保证是同一条物理连接，快照一致性不受影响），退出时提交，之后 Session touch 照常在读写事务里执行。任何时刻一个请求最多占一条连接，不会因为同时持有两条而在池耗尽时互等。列表、进度、导出都使用它。
- **管理导出**（`GET /management/review-cases/export?format=csv|xlsx` + 与列表相同的筛选）：
  - 行来自与 JSON 列表同一个"授权快照 → 过滤 → 排序"方法（`_filtered_summaries`），只是不分页。禁止另写指标算法；三种输出逐行逐字段一致由 `test_management_export_api.py` 固定。
  - 过滤后行数超过 `EXPORT_MAX_ROWS`（默认 10000）整体失败（422），不截断；响应在序列化完成后一次性返回，没有部分输出。
  - 时间一律按 `EXPORT_TIMEZONE`（默认 `Asia/Shanghai`）输出带 offset 的 ISO 8601；元数据含 generated_at、as_of、组织名称、筛选条件、时区、行数。
  - 表格公式注入：所有文本单元格以 `= + - @ \t \r` 开头时加 `'` 前缀（CSV 与 XLSX 一致）；XLSX 文本显式写成字符串类型；计数保持数字。XML 不可表示的控制字符替换为 U+FFFD。
  - CSV 为 UTF-8 + BOM；前几行是 `key,value` 元数据，空一行，再是表头与数据。XLSX 为 `review_cases` 与 `metadata` 两个 sheet。
  - 响应头：`Content-Disposition: attachment`（带时间戳的文件名）、`X-Content-Type-Options: nosniff`、`Cache-Control: no-store`。
  - 导出是数据外发：写一条 INFO `management_export`（`export_format`、`row_count`、`organization_id`、`actor_user_id`），不含任何行内容。暂不写平台审计事件。
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
- **锁序论证**：一个候选事务先 `SELECT … FOR KEY SHARE` 该 Organization 行，再对 Case（或 Action）`FOR NO KEY UPDATE`，再插入 Notification，此时 Notification FK 对收件人 `users` 行和 `organizations` 行加 `KEY SHARE`（后者已持有）。这与 Web 的 `Organization → Case → User` 同序，而且事务内从不跨候选累积锁，因此不会与 Web 成员操作成环。第一版（单事务扫完所有候选）会在 `Case₁ → User → Case₂ …` 处与 Web 成环；"先锁 Organization"这一步是实测补上的：Notification 对 `organizations` 的 FK 检查本身是一次后置的 `KEY SHARE`，与 Web 持有的 `Organization FOR UPDATE` 冲突。`tests/integration/test_reminder_sweep_race.py` 固定了无死锁的时序，并保留旧的单事务形态作为必然死锁的反例。
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
- 409 按冲突原因处理（界面表现见 [design.md](design.md#交互状态)）：
  - 生命周期已变化或并发冲突：先刷新，刷新成功后由用户重新确认操作。
  - `Idempotency-Key` 被不同请求复用（`isIdempotencyKeyReuse`）：说明当前内容与之前的创建请求不一致，保留草稿，不轮换键。
  - 唯一性等业务冲突：显示对应的业务提示。
- 网络中断或响应丢失导致的写入结果未知不属于 409，单独提示"未确认是否成功"。
- 任何情况都禁止自动重放写请求，包括结果未知的创建请求。一次创建尝试内持有同一个 `Idempotency-Key`，用户手动重试、双击和网络失败后重新提交都复用它，不随表单面板的卸载而重建。
- 不在本地长期保存业务状态的影子副本，写操作成功后刷新相关查询。
- 时间按 `Asia/Shanghai` 展示和解析（与导出、每日提醒一致），不随设备时区变化。展示和 `datetime-local` 输入的转换统一走 `web/src/product/format.ts`，输入区注明按上海时间；越界、不存在或夏令时跳过的时刻直接拒绝，不静默修正。`zh-cn` locale 只决定语言，不决定时区。
- UI 只用 antd 与 @ant-design/icons，不引入其他组件库或图标库（`web/.oxlintrc.json` 拦截已列出的常见库，其余由 review 把关）。主题只在 `web/src/app/theme.ts` 中配置，视觉、布局、组件、文案与迁移约束（证据上传、创建幂等、遗留样式隔离）见 [design.md](design.md)。

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

- 备份先 `pg_dump` 的 PostgreSQL 一致快照，再经 S3 协议镜像对象（不打包 Garage 内部卷）。已登记 Evidence 的对象由服务端生成 key、只写一次、不覆盖；正常且对象未丢失的情况下，后续镜像可包含 dump 之后新增的对象，形成 DB 引用集合的超集。它不是 DB + 对象的跨存储原子快照；缺失或 size/sha256 不一致会使 manifest 标记 `integrity: degraded`，产物仍保留，`backup.sh` 退出 3。完整目录表示产物已发布，不保证 integrity 为 ok。
- 一个备份包 = `database.dump` + `objects/` + `manifest.json`。manifest 记录 release SHA（运行中自建镜像 label 一致且等于 `EASYAUDIT_RELEASE`；backup 不读取 HEAD，检出对齐由操作者核对）、dump 的 alembic revision、各文件 sha256 与镜像信息；`backup_timestamp` 是 dump 开始时刻，不把后续对象镜像解释成同一原子时间点。
- 保留策略：按天数清理，但最近一份 `integrity: ok` 的备份永远保留，degraded 备份不能把它挤出保留窗口。备份每 12 小时一次，`check-freshness.sh` 监控"最近一份 ok 备份不超过 24h"；调度本身不保证 RPO。
- 恢复工具只写入空目标（DB 无非系统 schema 表、bucket 列举为空），不提供覆盖开关。Human Guidance 要求独立、隔离、可丢弃且经操作者确认的目标；empty-target guard 不验证部署身份，不能代替人工核对，也不授权删除 source 数据。三个入口在写入前都要求 manifest release 等于检出的 HEAD、`EASYAUDIT_RELEASE` 和已有 api 容器的镜像 label；仅 `environment` 还检查 tracked checkout 无改动，并在任何数据写入前同时检查 DB 和 bucket 为空。
- `database` 在 pg_restore 之后核对数据库 revision 与 manifest；`environment` 在 DB 和对象写入之后、应用启动之前，再核对 `alembic current = manifest revision = release head`。然后启动应用并运行 `verify.sh`；只有最终 verify 通过，才输出 `RESTORE OK`。degraded 包可以开始恢复且在写入前警告，但 environment 模式的最终 `verify --fail-degraded` 会失败，届时数据可能已写入且应用已启动。没有跨阶段自动回滚或失败后自动停应用的保证。
- 备份/恢复工具是接入 `backend` 网络的一次性容器（非 root、`cap_drop: ALL`、不发布端口），不在长驻容器里写文件，也不给 postgres 发布端口。
- secrets 和 TLS 证书不进备份包；和数据同盘的备份不算备份，异地拷贝由运维负责。
- 恢复演练（`deploy/backup/drill.sh`，CI job `backup-restore-drill`）是备份恢复的验收；演练通过网关 API 上传真实文件（含一个超过 part 大小的多段上传）来生成 Evidence，并从 bucket 读回对象核对 sha256；恢复后通过 API 下载每个 Evidence，把字节的 sha256 与元数据、与上传前本地文件的 sha256 比对，再跑 `verify-evidence` 和 `cleanup-evidence-orphans --dry-run`；故意删掉一个对象后，下载必须是带 request_id 的 500、`verify-evidence` 必须点名它。

## 证据文件上传

Evidence 元数据（`evidences` 表、`register_evidence`）早已存在；文件字节走对象存储。`POST /api/v1/action-items/{id}/evidence-uploads` 是登记 Evidence 的**唯一**入口，旧的 JSON 登记接口已删除（storage key、sha256、size 都由客户端提供，不可信）。

- **端口与适配器**：应用层的 `EvidenceObjectStore`（`put_stream` / `delete` / `exists` / `open_stream`，`review_core/application/evidence_storage.py`）；S3 适配器在 `infrastructure/object_storage.py`（boto3）。适配器把 SDK 异常换成不带 endpoint、bucket、凭证的 `ObjectStoreError`；凭证只从 `OBJECT_STORAGE_*_FILE` 指向的文件读取，只存在于 botocore 客户端里。botocore 显式配置 `connect_timeout`、`read_timeout`（单次 socket 操作的空闲上限，不是总截止时间）、`retries`（standard，`total_max_attempts = OBJECT_STORAGE_MAX_ATTEMPTS`，含首次请求；botocore 的 `max_attempts` 只算重试次数，不能用；part 是内存里的 bytes，重试安全）、path-style 寻址，并设 `proxies={}`（内部端点不走环境里的 HTTP(S)_PROXY）；校验和只在 API 要求时计算（`when_required`），因为我们自己对流计算 sha256，各 S3 兼容实现对 SDK 默认的尾部校验和支持不一。同步 SDK 的每次调用都在 `asyncio.to_thread` 里，不阻塞事件循环。
- **请求体就是文件字节**，不用 multipart：Starlette 的 multipart 会先把整个 body 落到临时文件，handler 才开始，大小限制来得太晚，且可以填满磁盘。`Content-Type` 是文件类型，`X-Evidence-Filename` 是 percent-encoded UTF-8 的原始文件名，`description` 是 query 参数。**文件名只是元数据**：去掉路径成分、控制字符和双向控制符，限制 255 字符，永远不参与存储 key。
- **三段事务**（`api/review_evidence_uploads.py`）：
  1. 认证后在短事务里**预授权**（`authorize_evidence_registration`：与 `register_evidence` 相同的权限与 Action 校验，不加锁），随即 `commit()` + `expunge_all()`。此后到响应前，这个请求不持有任何事务，也不占着池里的连接——否则大文件上传会被 `idle_in_transaction_session_timeout`（30s）杀掉连接。`tests/integration/test_evidence_upload_api.py` 在对象存储的 `put_stream` 里查 `pg_stat_activity` 断言这一点（含真实 Cookie 认证链路）。
  2. 流式写对象：`request.stream()` 逐块读取，边读边算 SHA-256 和大小，满 8 MiB 就作为一个 part 上传（小于一个 part 的文件用单次 `PutObject`）。内存上限是约一个 part 加一个输入块，与文件大小无关；不先读进内存，也不先落盘。key 由服务端生成：`org/{organization_id}/evidence/{uuid4}`，只写一次，不覆盖（备份一致性模型的前提）。
  3. 新的短事务调用 `register_evidence`，传入**服务端计算的** key、size、sha256。它重新取用户（上传期间可能已被停用）、重新授权、按 `ReviewCase → Finding → Action` 加锁（Case 锁内重新授权）、写元数据和 Activity，然后提交。
- **对象只在登记确定回滚时才删除**：登记在工作线程里跑，线程无法停止，请求被取消不等于登记没发生。所以登记线程**自己持有 Session**（线程内创建、提交或回滚、关闭，不碰请求作用域的 Session），`_register_and_settle` 用 task 包住它：已提交 → 保留对象；确定回滚 → 删除；**`COMMIT` 报错一律视为结果未知 → 保留对象**（之后的 `rollback` 只是尽力清理，它自己报错也只记日志，不能改变这个结论），记 `evidence_registration_outcome_unknown`。请求被取消后等待登记结果的时间**有上限**：`DB_STATEMENT_TIMEOUT_MS + DB_LOCK_TIMEOUT_MS + 5s`；超时同样按结果未知处理——保留对象，记 `evidence_registration_unsettled`（只有 `storage_key`），重新抛出取消，线程留在后台自己跑完。永远不会出现"有元数据、没对象"，最坏是没有元数据的孤儿对象，由孤儿清理处理。后台线程的寿命受"数据库黑洞下业务请求没有客户端截止时间"这一已接受风险（见"数据库预算"）约束，不另加机制。
- **失败清理**：写对象失败或中途超限，适配器 abort multipart，什么都不留；第 3 段失败（授权变化 403/404、生命周期变化 409/422、DB 错误），**尽力删除**刚写的对象，再返回原来的错误。删除也失败时对象成为孤儿，记 WARNING `evidence_object_orphaned`，字段只有 `storage_key`（日志白名单为此新增了 `storage_key`；key 里没有文件名和用户输入），由孤儿清理处理（见下）。进程崩溃遗留的未完成 multipart 同样如此。
- **限制**：`EVIDENCE_MAX_BYTES`（默认 25 MiB）。`Content-Length` 超限在读 body 之前就 413；没有 `Content-Length`（chunked）时累计到超限立即中止并 413。网关 Caddy 对 `/api/v1/*` 设 `request_body max_size`（26 MiB，略大于应用上限，纵深防御：它在上游读取 body 时才生效，所以不替代应用自己的 `Content-Length` 检查；改应用上限时同步改 `deploy/Caddyfile`，`tests/unit/test_deploy_compose.py` 检查两者关系，`smoke.sh` 用登录接口验证它真的生效）。类型白名单 `EVIDENCE_ALLOWED_CONTENT_TYPES`（默认 pdf、png、jpeg、docx、xlsx、pptx、txt、csv；只能是代码里有扩展名映射的类型，启动时校验）；不在白名单或扩展名与类型不一致 → 415；文件名为空或编码非法、空文件 → 422。
- **提前拒绝的代价**：413/415/422/403 在读 body 之前就返回，客户端可能还在发送，此时连接会被关闭，浏览器看到的可能是网络错误而不是状态码；前端对此有专门提示，且不自动重试。
- 对象存储不可用或未配置：上传 503（`object_storage_operation_failed` WARNING，字段只有 `component`、`reason`），不写元数据。

## Evidence 下载

`GET /api/v1/evidences/{evidence_id}/content`（`api/review_evidence_downloads.py`）。

- **授权**：按 `(actor.organization_id, evidence_id)` 查元数据（不按全局 id 查），再对其 Action/Finding 上下文做与 `list_evidences` 相同的 `view_finding` 判断（`RectificationService.get_evidence_for_download`）。不存在、跨组织、无权限（含未激活用户）**一律同一个 404**（`Evidence not found`），并且这些情况下完全没有访问对象存储。不用 403：403 会告诉调用者"这个 id 存在但你不能看"，Evidence UUID 因此可以被拿来探测对象是否存在。知道 storage_key 没有任何用处：它不是路由参数，对象存储也不对外。
- **事务边界与上传一致**：`_authorize` 在短事务里完成认证、授权、读元数据，然后 `commit()` + `expunge_all()`。**对象是在响应对象被发送时才打开的**（`EvidenceDownloadResponse.__call__`），此时所有 `scope="function"` 的依赖（含 DB Session 与 Session `touch`）都已退出，所以流式期间不持有任何事务、不占池里的连接；`tests/integration/test_evidence_download_api.py` 在流式读取的每个块之间查 `pg_stat_activity`（含真实 Cookie 认证链路）。
- **流式与资源释放**：端口 `open_stream(key)` 是 async 方法，先发出 `GetObject`，对象缺失（`ObjectNotFoundError`）或存储失败（`ObjectStoreError`）在**第一个块之前**就抛出，所以响应状态还能选择；返回的流按 64 KiB 一块读取（每次读在 `asyncio.to_thread` 里，内存与对象大小无关），必须 `aclose()`。响应在正常结束、客户端断开（ASGI 2.3 的 disconnect 监听与 ≥2.4 的 `OSError` 两种）、取消、异常的**所有**出口都 `aclose()`：close 在被 `asyncio.shield` 保护的线程调用里执行，不会被取消打断；被取消的那次读线程无法被停止，结果丢弃；它何时结束取决于 botocore 的 `connect_timeout`/`read_timeout`，而它们只是单次 socket 操作的空闲上限，不是总截止时间（与 4A 同一类已接受风险）。`GetObject` 本身在返回之前被取消时，`open_stream` 用 shield 保住 GET 任务，并给它挂 done-callback：Body 一返回就被关闭，不需要（也不做）有上限的等待。
- **响应头**：`Content-Disposition: attachment; filename="<ASCII 回退>"; filename*=UTF-8''<percent-encoded>`（回退里非 ASCII、引号、反斜杠、分号、`%` 一律换成 `_`，真实文件名只出现在 percent-encoded 的 `filename*` 里，所以带引号或分号的名字不能破坏头）；`X-Content-Type-Options: nosniff`；`Cache-Control: private, no-store`；防御性的 `Content-Security-Policy: default-src 'none'; sandbox`；`Content-Length` 取元数据的 `size_bytes`；`Content-Type` 是元数据里的类型（仅当它属于代码里 `EXTENSIONS_BY_CONTENT_TYPE` 的白名单），否则 `application/octet-stream`。
- **元数据存在但对象缺失是 Evidence 丢失**，属于试点停止条件，必须被监控发现：返回 **500**（`{"detail", "request_id"}`）并记 ERROR `evidence_object_missing`（字段只有 `evidence_id`、`storage_key`，两者都在日志白名单里）。**不返回 404**：404 会把数据丢失伪装成"没有这个文件"。授权在前，所以无权限的人看到的仍然只是 404。对象存储本身不可用是 503（WARNING `object_storage_operation_failed`），与丢失区分开。
- **下载不重算 sha256，但在发送任何响应头之前比较存储报告的 `ContentLength` 与元数据的 `size_bytes`。** 重算要把对象读两遍、且字节已经在发送，没法再改变响应；而响应头承诺了 `Content-Length`：对象偏短时客户端会把截断的文件当作成功下载，所以不一致按完整性故障处理——**500（带 request_id），ERROR `evidence_object_size_mismatch`（只有 `evidence_id`、`storage_key`），不发送任何内容**。同样长度、字节不同的损坏下载侧不检测，由 `verify-evidence` 负责。
- **存储没有配置时，认证与授权先于 503**：未知、跨组织、无权限一律 404，只有授权通过之后才是 503。

## Evidence 孤儿清理与完整性校验

两个运维命令（`review_core/application/evidence_maintenance.py`，由 `cli.py` 接线；都不在请求路径上，也都不在读对象时持有数据库事务）。

- **`easyaudit-next cleanup-evidence-orphans [--min-age-hours 24] [--dry-run]`**：只处理 `org/*/evidence/` 前缀。分批列出对象，与 `evidences.storage_key` 比对，**未被引用且 `LastModified` 早于 min-age** 的才是可删除的孤儿。**删除前逐个 key 在新的短事务里再查一次**，仍未被引用才删。任何情况下被引用的对象都不删。输出一行 JSON：`scanned`、`orphans`（未被引用的，含太年轻的）、`deleted`、`kept_young`、`multipart_stale`、`multipart_aborted`、`skipped_referenced`（复查时发现已被引用）、`failed`、`max_delete`、`deleted_but_registered`、`refused`；`failed`、`refused`、`deleted_but_registered` 任一非零时退出码为 1。`--min-age-hours`：非 dry-run 必须 ≥ 24，dry-run 允许 ≥ 1，更小的值会和进行中的上传竞争。**写操作前的三条整体拒绝保护**（非 dry-run，任一触发保证零删除、零中止、退出码 1、JSON `refused` 写明原因；dry-run 不判断这些保护）：分开为**列举前的 revision 前置检查**与**完整列举后的两项保护**。前置检查 `revision_mismatch` 读出 `alembic_version` 的**全部**行，要求集合严格等于 `{head}`；在列举对象和 multipart 之前执行，不匹配立即拒绝返回，此时输出中的 `scanned=0`、`multipart_stale=0` 等各项计数为初始值，**不能用来判断桶里有什么**。通过前置检查后，命令在**第一次写操作之前完整列举**对象和未完成 multipart、累计完整候选集，随后检查 `no_evidence_rows`（`evidences` 为 0 行而桶里 evidence 前缀下扫描到对象 `scanned > 0`：几乎肯定连错库或恢复未完成）与 `too_many_deletions`（候选数超过 `--max-delete`，默认 100；正常运行孤儿很少，一次很多说明出问题，人工确认后调大上限重跑）。任一列举失败或保护拒绝均不会有任何删除或中止。**这三项保护是启发式的，不绑定部署身份**：部署需确保 CLI 使用的数据库与对象存储配置属于同一环境（错桶 + 同 revision + 候选数不超限时仍可能删错）。
  - **为什么是 min-age 加逐 key 复查**：孤儿判定是"此刻没有行引用它"，但"此刻"有两类例外——还在进行的上传（对象已写完、登记事务尚未提交）以及 4A 的"结果未知"（登记线程无法取消，可能晚提交，等待它的时间上限是 `DB_STATEMENT_TIMEOUT_MS + DB_LOCK_TIMEOUT_MS + 5s`）。min-age（默认 24 小时，远大于这些时间）让这两类都不会被碰到；逐 key 复查再收窄"列举之后、删除之前"的窗口。复查之后到 `DeleteObject` 之间仍有窗口（见下一条）。`evidences.storage_key` 没有索引，试点规模下的顺序扫描可以接受，数据量大了再加。
  - **已接受的窗口（试点期）：复查之后才提交的晚登记。** 若一条登记在逐 key 复查之后、`DeleteObject` 之前提交，对象被删，留下"有元数据没对象"。触发条件：登记被延迟超过 min-age（≥ 24h）——登记线程无法停止，只有 DB 黑洞类故障（见"数据库预算"）才可能拖这么久，与 4A 已接受的风险同类。**检测而非预防**：每次删除之后立即再查一次 DB（`DeleteObject` 报错时结果未知，同样复查，并要求对象确已不存在或状态读不出才算事故），命中则**当场**写 ERROR `evidence_object_deleted_while_registered`（只有 `storage_key`、`evidence_id`，不等后续步骤成败）、计入 JSON `deleted_but_registered`、退出码非零，运维据此从备份恢复该对象。命令中途因异常失败时，stdout 的 JSON 仍输出已累计的计数，并带 `error`（只有异常类型）。根治需要让登记与清理通过唯一约束共享一张 key 认领表，要迁移并改 4A 的登记路径，已列入 roadmap「之后」。
  - **时钟与年龄**：min-age 依赖对象存储与运行命令的主机时钟一致，部署时保持时钟同步；multipart 的 `Initiated` 年龄不代表它不活跃，单次上传的耗时必须远小于 min-age。
  - **未完成的 multipart**：同一个命令通过 `ListMultipartUploads` 中止 `Initiated` 早于 min-age 的上传（同样只限 evidence 前缀）。没有改用 bucket lifecycle 的 `AbortIncompleteMultipartUpload`：Garage v2.4.1 对它的支持无法在本仓库的环境里验证（官方兼容性文档只说"部分实现"且已多年未更新），而且 lifecycle 的粒度是天、需要在 Garage 容器里额外配置 S3 客户端；CLI 方式可以用 moto 测试、粒度是小时、与对象清理共用 min-age。
  - **和备份一致性模型（1B）的关系**：备份先 `pg_dump` 再镜像对象，所以备份里的对象集合是 DB 引用集合的超集。从备份恢复后，bucket 里多出来的对象就是孤儿，它们在 min-age 之后被这个命令正确清理；恢复本身不需要处理它们。
  - **运维注意**：三条保护触发之后先查原因（连对库了吗、迁移到 head 了吗、恢复完成了吗），确认无误才用 `--max-delete` 放大上限重跑；首次在新环境仍建议先 `--dry-run`。
- **`easyaudit-next verify-evidence [--organization-id UUID] [--limit N]`**：对每条 Evidence 确认对象存在、流式重算 sha256 与大小并与元数据比较（数据库按 id 分批读取，每批读完事务即结束）。输出一行 JSON：`checked` 和 `problems`（`evidence_id` + `missing` / `size_mismatch` / `sha256_mismatch` / `read_error`），有任何不一致退出码为 1。用于恢复后的验证和故障诊断；它读全部对象，不是例行监控。与 `deploy/backup/verify.sh`（以某份备份的 manifest 为基准，校验备份包和"环境是否还原成这份备份"）互补：`verify-evidence` 不需要备份包，只检查线上对象与数据库元数据是否一致。

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
- `observability`、`readiness` 只能被 `api/`、`management/api.py`（HTTP 适配层）、`main.py`、`serve.py` 使用，Review Core 与 Platform 不依赖它们（`scripts/check_architecture.py` 强制）。

## 明确不做

微服务、分布式事务、消息总线、以 Redis 作为业务真相、通用分布式锁、BPMN 或流程设计器、通用表单构建器、运行时实体设计器、自定义仪表盘、匿名责任令牌、督办实体、原生移动端、由 AI 生成业务真相。
