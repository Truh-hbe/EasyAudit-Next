# 配置、生效与凭证维护

本页是配置/凭证维护的 canonical reference；部署、升级和恢复步骤只在 [deploy/README.md](../../deploy/README.md)。事实来源为 [Settings](../../src/easyaudit_next/platform/settings.py)、[Compose](../../deploy/compose.yaml)、[API entrypoint](../../deploy/docker-entrypoint.sh)、[Garage entrypoint](../../deploy/object-storage/entrypoint.sh)、[main lifespan](../../src/easyaudit_next/main.py) 与 [配置测试](../../tests/unit/platform/test_settings.py)。

## 六层配置与优先级

| 层 | 实际输入与作用 | 生效边界 |
| --- | --- | --- |
| 本地开发 dotenv | 根 `.env.example` 是模板；Settings 从进程工作目录的 `.env` 读取，大小写不敏感，未知项忽略 | 进程环境覆盖 dotenv，再落到代码默认；文件不是动态配置服务 |
| Compose interpolation | `deploy/.env.example` 可复制为 `deploy/.env`；部署 `-f deploy/compose.yaml` 的 project directory 为 deploy，默认 dotenv 从该目录发现（除非用 --env-file / COMPOSE_ENV_FILES / COMPOSE_DISABLE_ENV_FILE 改变发现方式） | Shell export 覆盖文件；路径/端口/release 等只有在 Compose 引用时展开，不等于向 api 容器注入所有变量 |
| Container environment | Compose 的 `environment` 显式给 api 数据库离散字段、对象 endpoint/bucket/region/credential 文件路径和 `FORWARDED_ALLOW_IPS`；migrate 只获数据库输入 | 镜像不复制根 `.env`；宿主机写 `APP_ENV`、`DB_POOL_SIZE` 等并不会自动传入容器 |
| 文件挂载 | Docker secrets 按文件只读挂载，宿主机父目录 0700，容器需能读取文件 | 宿主机替换文件的路径/inode 不保证现有 bind mount 获得新内容；需要重建消费容器 |
| 应用 Settings | API/CLI/Alembic 调用 `get_settings()`；API entrypoint 在没有非空 `DATABASE_URL` 时才从 `POSTGRES_PASSWORD_FILE` 生成带密码的 URL | `get_settings()` 为进程内 `lru_cache`；直接提供 DATABASE_URL 会绕过该文件组装 |
| 构造后的资源 | API engine、S3 client、Evidence policy、readiness 的 expected Alembic head 在进程内构造/缓存；S3 凭证启动时从文件读入 | 编辑 host 文件 ≠ 容器收到新值 ≠ 进程重载；重新启动进程，环境/挂载变化则重建容器 |

`deploy/.env` **不会被 Bash 脚本 source**。备份/恢复/演练所需的 `EASYAUDIT_*`、`COMPOSE_PROJECT_NAME` 必须在执行脚本的 Shell 或 systemd unit 中明确 export/Environment；尤其 `restore_environment` 的 secret/cert 前置文件检查读 Shell 值。Compose 虽可能从 dotenv 读取路径，Shell 检查不会同步读取它。为两者提供相同的显式绝对路径，避免以两套默认值操作。

Compose 自身的 dotenv/interpolation 与 container environment 区别参见 [Docker CLI 的官方规则](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)；本页 Shell export 示例用于固定实际身份，不依赖未核实的其他 dotenv 发现设置。

`DATABASE_URL` 含密码，应按 secret 处理；不要输出完整 `docker compose config`、容器环境或 URL 到日志/Issue。路径型变量只含路径，但对应文件内容仍是 secret。客户端凭证没有从普通 `OBJECT_STORAGE_ACCESS_KEY_ID` / `OBJECT_STORAGE_SECRET_ACCESS_KEY` 环境变量读取的入口。

## Settings 运维参考

以下是代码默认，**不是 `.env.example` 中被修改后的值**。来源统一为进程环境/本地 dotenv/代码默认；部署是否覆盖由 Compose 实际 `environment` 决定。全部项目修改后都需新进程；要改变容器环境需 recreate。未写出额外校验的字符串/整数只有类型解析约束，不凭名称补校验。

| Name | 默认 | 校验 / 消费位置 / 部署意义 |
| --- | --- | --- |
| `APP_ENV` | `development` | 字符串；ready 在非 development 时拒绝内置开发 DATABASE_URL。部署 Compose 未注入此项，仍取默认，不把私网拓扑解释成已设置 production |
| `APP_HOST` | `0.0.0.0` | 字符串；serve 的监听地址 |
| `APP_PORT` | `8000` | int；serve 的监听端口。Compose healthcheck 和 gateway 固定访问 8000，单改应用值会破坏路由 |
| `DATABASE_URL` | `postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit` | Secret；Settings 字符串，engine/ready 再解析 URL；Compose 由 entrypoint 生成内部 postgres:5432/easyaudit 的 URL。用于 API、CLI、迁移 |
| `SESSION_COOKIE_NAME` | `__Host-easyaudit_session` | Literal 固定；Secure、HttpOnly、SameSite=strict、Path=/ 由 API 设置，需要受信任 HTTPS |
| `SESSION_TTL_SECONDS` | `43200` | 300–2592000；新 Session 的 expires_at。不重写已存在 Session 的期限 |
| `SESSION_TOUCH_INTERVAL_SECONDS` | `300` | 0–3600；last_seen_at 更新间隔，不影响授权/Session 到期 |
| `LOGIN_THROTTLE_WINDOW_SECONDS` | `900` | 60–86400；固定窗口登录限流 |
| `LOGIN_THROTTLE_LOGIN_NAME_LIMIT` | `5` | ≥1；登录名窗口次数 |
| `LOGIN_THROTTLE_IP_LIMIT` | `50` | ≥1；IP 窗口次数；变更需结合可信代理地址 |
| `DB_POOL_SIZE` | `10` | 1–100；业务 engine 池 |
| `DB_MAX_OVERFLOW` | `5` | 0–100；池额外连接；与 DB_POOL_SIZE 之和须 ≥2 |
| `DB_POOL_TIMEOUT_SECONDS` | `10.0` | >0、≤120；等连接池时限（秒） |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | ≥-1；回收连接年龄，-1 禁用回收 |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | 1–60；libpq 建连时限；URL 同名参数优先 |
| `DB_TCP_USER_TIMEOUT_MS` | `15000` | ≥1000；已建连接 TCP 探测，平台 socket 支持是前提，不是查询总截止时间 |
| `DB_KEEPALIVES_IDLE_SECONDS` | `10` | ≥1；TCP keepalive 空闲 |
| `DB_KEEPALIVES_INTERVAL_SECONDS` | `5` | ≥1；keepalive 间隔 |
| `DB_KEEPALIVES_COUNT` | `3` | ≥1；keepalive 次数；三个 keepalive 项的 URL 同名参数优先 |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | ≥1；业务连接单语句限时 |
| `DB_LOCK_TIMEOUT_MS` | `5000` | ≥1；业务连接锁等待限时，建议低于 statement timeout，但 Settings 不校验二者大小关系 |
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` | `30000` | ≥1；业务连接事务空闲限时 |
| `READINESS_TIMEOUT_SECONDS` | `2.0` | >0、≤10；独立 ready 探测截止时间，不修改业务请求预算 |
| `OBJECT_STORAGE_ENDPOINT` | 空字符串 | 仅 http(s) origin，可尾随 `/`；禁止 path prefix、query、fragment、userinfo；空值会使 store 未配置、上传 503 / ready 失败。Compose 为 `http://object-storage:3900` |
| `OBJECT_STORAGE_BUCKET` | `easyaudit-evidence` | 字符串；S3 client。Compose/Garage/backup 固定此 bucket，不能只改 API 指向别的 bucket |
| `OBJECT_STORAGE_REGION` | `garage` | 字符串；S3 client，Compose/Garage/rclone 同值 |
| `OBJECT_STORAGE_ACCESS_KEY_ID_FILE` | 空字符串 | Secret 文件路径；S3 client 启动时读取并 strip；Compose 指向 `/run/secrets/s3_access_key_id` |
| `OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE` | 空字符串 | Secret 文件路径；同上，Compose 指向 `/run/secrets/s3_secret_access_key`；文件不可用时不构造可用 store |
| `OBJECT_STORAGE_CONNECT_TIMEOUT_SECONDS` | `5.0` | >0、≤60；S3 connect 单次操作限时 |
| `OBJECT_STORAGE_READ_TIMEOUT_SECONDS` | `30.0` | >0、≤300；S3 read socket 空闲限时，不是总传输截止时间 |
| `OBJECT_STORAGE_MAX_ATTEMPTS` | `3` | 1–10；standard retry 的总尝试次数，包含首次 |
| `EVIDENCE_MAX_BYTES` | `26214400`（25 MiB） | ≥1；上传上限；Caddy 当前 body 上限 26 MiB。调整必须核对 gateway，不只改 API |
| `EVIDENCE_ALLOWED_CONTENT_TYPES` | pdf/png/jpeg/docx/xlsx/pptx/txt/csv 对应 MIME 的逗号串 | Settings 解析字符串；Evidence policy 启动时要求非空且每项有扩展名映射。完整 MIME 见下；根模板的示例串只含其中五种，启用该串会缩小白名单 |
| `REMINDER_TIMEZONE` | `Asia/Shanghai` | IANA ZoneInfo 校验；CLI 默认 daily occurrence key 的日期，与 systemd timer 的时区分别配置 |
| `EXPORT_TIMEZONE` | `Asia/Shanghai` | IANA ZoneInfo 校验；CSV/XLSX 输出时间格式 |
| `EXPORT_MAX_ROWS` | `10000` | ≥1；导出行数上限，不是投影阶段内存/耗时上限 |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL，转大写；JSON 日志配置 |

默认 MIME 串：`application/pdf,image/png,image/jpeg,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/plain,text/csv`。

DB 的 statement/lock/idle 设置由业务 engine 追加至 libpq options，同名以应用配置为准；Alembic 自建 NullPool engine，不使用这些业务超时。连接预算和 HTTP 超时语义见 [架构](../architecture.md#数据库预算)。

### Settings 以外的输入

| 输入 | 消费与默认 / 校验 | 生效与注意事项 |
| --- | --- | --- |
| `EASYAUDIT_RELEASE` | Compose 镜像 tag/label 必填；backup 核对运行中 api/web/object-storage label 与 `EASYAUDIT_RELEASE` 一致（不读取 HEAD，检出是否对齐由操作者核对）；restore 核对 manifest 与 HEAD/env/已有 api label | 每个 Shell/unit 显式 export；不是长期写死在模板里的值 |
| `COMPOSE_PROJECT_NAME` | Docker Compose project；Compose 默认 name=`easyaudit`；drill/smoke 在脚本中自行指定固定测试 project | 所有命令和脚本必须使用已确认的同一 project；改名不会自动隔离外部配置或已有数据 |
| `EASYAUDIT_SECRETS_DIR` / `EASYAUDIT_CERTS_DIR` | Compose 默认 `deploy/secrets` / `deploy/certs`；restore Bash 检查 Shell 值或自身 deploy 路径 | 使用绝对路径并 export；文件或挂载改变时重建消费者 |
| `EASYAUDIT_HTTPS_PORT` | 默认 443，展开为 gateway 发布端口；工具不保证目标端口空闲 | 试点保留 443；测试可指定空闲端口，recreate gateway |
| `POSTGRES_*` / `POSTGRES_PASSWORD_FILE` | Compose 给 api/migrate 离散连接信息，postgres 官方镜像读取密码文件；API entrypoint 仅在无 DATABASE_URL 时组装 | 不打印密码或生成后的 URL；首次初始化与既有数据库密码变更不同 |
| `FORWARDED_ALLOW_IPS` | api 为 `172.30.10.10`，serve/uvicorn 信任代理来源 | 必须与 gateway 地址一起审查；不可扩大成 `*` |
| `S3_BUCKET` / `RCLONE_CONFIG_EA_*` | Garage/rclone 初始 bucket/endpoint/region；secret 由 entrypoint 读入 rclone 进程环境 | 与 API 和备份工具同环境；修改一个消费者不改变服务端凭证 |
| `EASYAUDIT_BACKUP_DIR` | backup/freshness Shell 必填；backup 要求 0700、调用者拥有、非 root | 与数据卷不同盘；dotenv 中写值不代替 Shell export |
| `EASYAUDIT_BACKUP_RETENTION_DAYS` | 14；正整数；新包发布后清理过期包，最新 integrity-ok 包保留 | 保留清理会删除过期备份，修改前核对 backup root 身份 |
| `EASYAUDIT_BACKUP_MAX_AGE_HOURS` | freshness 默认 24；只计算最新 integrity-ok backup_timestamp | 探针失败不等于已配置外部告警 |
| `DRILL_RECORD` / `DRILL_RTO_LIMIT_SECONDS` | drill 记录默认当前目录 restore-drill-record.json；RTO 限值 14400，正整数 | 仅独立可丢弃测试环境；限值不是目标机已达标证据 |

## 配置变更与激活

先按部署入口确认当前 project、Docker daemon、release 和消费服务，保留旧配置/文件在受限目录并记录失败回退点。区分更改值、容器注入、应用读取和服务端凭证四个动作。

对于 base Compose 没有显式注入的 Settings，直接编辑 `deploy/.env` 无效。维护者需审核 Compose environment override；例如宿主机上另存的配置文件可只为 api 注入 `APP_ENV` / `LOG_LEVEL`。这属于操作者配置，不是仓库新增能力：

```yaml
# /srv/easyaudit-config/settings.override.yaml（需操作者审查并实际创建）
services:
  api:
    environment:
      APP_ENV: pilot
      LOG_LEVEL: INFO
```

```bash
# 只对已确认的当前部署；EASYAUDIT_RELEASE、project、secret/cert 绝对路径与部署入口一致。
docker compose -f deploy/compose.yaml -f /srv/easyaudit-config/settings.override.yaml \
  up -d --no-deps --force-recreate api
```

`APP_ENV=pilot` 只触发非 development 配置检查，不授予上线资格。override 必须在后续相同操作中继续使用；CLI 若使用 `run api` 会取该 api 配置，新进程读取新 Settings。迁移若需同一环境输入，应明确配置 migrate；不要只改 API 的数据库/bucket/release。

仓库 backup/restore/smoke/drill 脚本始终显式 `-f deploy/compose.yaml`，不自动合并上述 override 或因设置 `COMPOSE_FILE` 而使用它；相关 systemd 示例也使用 base 文件。任何涉及工具共用数据库、bucket、secret、project、网段的 override，都必须先另行核实全部消费者，不能按本例声称整套工具已经适配。单改日志级别不应重建数据库或对象卷。

验证：使用部署入口的内部 live/ready、HTTPS 登录及相应实际业务操作；S3 凭证用实际授权上传/下载与 `verify-evidence` 检查，ready 的 unsigned HEAD 只证明 endpoint 可达。失败时恢复之前受限保存的配置，并用相同 Compose 文件重建消费者；这不回滚服务端已经更改的凭证或数据库。

## 凭证轮换边界

对每类轮换，记录 provider/service 更新、文件替换、消费者 recreate、新凭证验证、旧凭证保留/撤销和失败回退；这些是不同阶段。以下“未建立”表示不能凭仓库初始生成命令宣称安全在线轮换。

| 凭证 | 仓库支持的事实 | 变更、验证与失败边界 |
| --- | --- | --- |
| PostgreSQL password | `POSTGRES_PASSWORD_FILE` 用于初始数据库凭证及消费者连接；entrypoint 读取文件生成 URL | **No repository-backed rotation procedure is currently established**：既有 PG 数据卷中的账号密码不会因替换文件而自动更新。服务端更新、连接交接、旧密码退休/回退为 UNVERIFIED，需维护者程序；只重建 api/migrate/db-tool 可能造成认证失败。不要删除 PG 卷“激活”密码 |
| Garage RPC secret | garage.toml 指向 `/run/secrets/garage_rpc_secret`，本拓扑为单节点 | 在线轮换/失配恢复/旧 secret 退休 **UNVERIFIED — maintainer/operator procedure required**。不能只重建服务器就承诺无损轮换 |
| S3 key ID / secret | 初次启动导入 key 并赋 bucket 权限；`key info KEY_ID` 已成功时跳过 import；API client 一次构造 | 同 ID 替换 secret 文件不会更新 Garage 旧 key；新 ID 的导入也不证明旧 key 撤销。安全轮换、provider 回退及旧 key 退休流程 **NOT ESTABLISHED**。初始生成格式为 GK+24 hex（ID）、64 hex（secret）；核对 API、rclone 和 Garage 消费者，不输出值 |
| TLS certificate/key | Caddy 按 secret 文件读取现有证书；内部 CA 证书需匹配访问域名，客户端信任 CA | 维护者先验证证书/key 匹配、域名/期限/信任链并受限保存旧对，然后按部署入口的权限安装新对；在已确认 project 用 `$DC up -d --no-deps --force-recreate gateway` 重建。HTTPS 客户端验证新证书及登录；失败恢复旧对再重建。仓库没有 CA 签发/撤销/自动续期/无停机切换工具 |
| 应用账号密码/Session | 管理员 UI/API reset credential，用户 change-password；Session 可 logout/revoke，密码 Argon2id 存数据库 | 使用管理设置和改密流程、验证本人新密码登录及 Session 行为；这不是一个可直接修改的全局 signing secret。数据库密码哈希随备份恢复；不得凭文件替换假定所有 Session 撤销 |

TLS 行的 `$DC` 使用 [部署入口](../../deploy/README.md#命令环境与身份) 的定义及当前确认的 project；若用 override，需使用相同文件集合。证书更换的回退不代表应用/数据库 rollback 已建立。

Garage 初始 `key import` 将 secret 放入 argv，容器和主机上可读进程参数的账号/采集器在该时段可能看到它；entrypoint 已记录此限制。宿主机必须可信，按运维程序控制 `/proc` 可见性（例如 hidepid）、采集器与日志访问；仓库未自动配置该主机策略，不将“文件挂载”写成任何位置均不可见。
