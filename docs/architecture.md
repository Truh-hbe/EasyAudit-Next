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

## 部署

配置在 `deploy/`，规则由 `tests/unit/test_deploy_compose.py` 和 `deploy/smoke.sh` 强制：

- 只有 HTTPS 网关对外，且只发布 443。数据库、API、对象存储只在网络内部可达；`backend` 网络是 `internal`。
- 数据库迁移必须显式执行（`migrate` 服务），API 启动时不迁移。
- 所有容器非 root 运行；镜像固定到具体版本，不使用 `latest`。
- 密钥只通过未提交的文件（Docker secrets / `*_FILE`）注入，不写进 compose 或镜像。
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
- 恢复演练（`deploy/backup/drill.sh`，CI job `backup-restore-drill`）是备份恢复的验收；Pilot-4B 上线下载端点后，必须把"通过 API 下载 Evidence"加进演练。

## 可观测性

- **Health 不对外。** `/health/live`、`/health/ready` 挂在根路径，不在 `/api/v1` 下；网关只转发 `/api/v1/*`，所以外部访问不到（`deploy/smoke.sh` 断言）。旧的 `/health` 已删除。
- `live` 只表示进程能响应，不访问数据库或任何外部依赖。`ready` 检查三项，全部通过才 200，否则 503：数据库 `SELECT 1`（连接和语句超时各 2 秒，用独立、不池化的 engine）、Alembic 当前 revision 等于镜像内脚本的 head、必需配置存在。响应体只有各项的 `ok`/`fail`，不带 DSN、revision、错误消息；细节写日志。
- 对象存储暂不纳入 `ready`，因为应用尚未使用它；Pilot-4A 接入 Evidence 上传时再加进去。
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
