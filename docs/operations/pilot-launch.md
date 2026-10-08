# 试点上线检查清单

上线前逐项勾选并签字。命令在仓库根目录执行，约定与 [部署手册](../../deploy/README.md) 一致：`DC="docker compose -f deploy/compose.yaml"`，且已 export `EASYAUDIT_RELEASE`、`COMPOSE_PROJECT_NAME`、`EASYAUDIT_SECRETS_DIR`、`EASYAUDIT_CERTS_DIR`。尖括号和 `____` 由维护者填写。

## 1. 版本

| ☐ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☐ | 部署的 release 与 main 提交对应 | `git rev-parse HEAD`；`docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$(docker inspect --format '{{.Image}}' "$($DC ps -q api)")"`（`web`、`object-storage` 同理）；`git merge-base --is-ancestor <release> origin/main` | 三个镜像 label 一致，等于 `EASYAUDIT_RELEASE` 和检出 HEAD，且该提交在 `origin/main` 上；工作区干净（`git diff --quiet HEAD`） |
| ☐ | 数据库迁移到 head | `$DC run --rm --no-deps -T migrate alembic current`；`... alembic heads` | 两者输出同一个 revision |
| ☐ | 配置与部署入口一致 | 对照 [配置参考](configuration.md)：systemd unit 与手动命令使用同一 `EASYAUDIT_RELEASE`、project、secrets/certs 路径；`APP_ENV` 非 `development` | 无差异；`/health/ready` 的 `migrations` 为 `ok` |

记录：release `<sha>`；revision `<rev>`。

## 2. 备份新鲜度

| ☐ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☐ | 最近一份 `integrity: ok` 备份的时间 | `EASYAUDIT_BACKUP_DIR=<backup-root> deploy/backup/check-freshness.sh`；`systemctl list-timers easyaudit-backup.timer easyaudit-backup-freshness.timer` | 退出 0；`backup_timestamp` 距今 ≤ ____ 小时（默认 `EASYAUDIT_BACKUP_MAX_AGE_HOURS=24`） |
| ☐ | 最近一次备份 service 成功 | `systemctl show easyaudit-backup.service -p Result -p ExecMainStatus`；`journalctl -u easyaudit-backup.service -n 50 --no-pager` | `Result=success`；不是 exit 3（degraded） |
| ☐ | 位置与大小 | `ls -ld <backup-root>`；`du -sh <backup-root>/easyaudit-backup-*` | 备份目录权限 0700、与数据卷不在同一块盘；最新包大小与前几份同量级（不为空、不骤降），数值 ____ |
| ☐ | 备份包自身完整 | `deploy/backup/verify.sh <最新备份目录> --bundle-only` | 退出 0；`manifest.json` 的 `release_sha` / `alembic_revision` 与第 1 节一致或可解释 |

## 3. 恢复演练

| ☐ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☐ | 在目标机器、按实际数据量做过一次演练 | 在专用可丢弃 Docker 主机运行 `deploy/backup/drill.sh`（固定 project `easyaudit-drill`，会 `down -v`，绝不能在生产主机运行）；记录 `restore-drill-record.json`（`result`、`actual_rto_seconds`、`backup_timestamp`、`release_sha`） | `result` 通过；`actual_rto_seconds` ≤ `DRILL_RTO_LIMIT_SECONDS`（默认 14400，设计目标 RTO ≤ 4h）；演练使用的 release 即本次上线 release。CI 的 `backup-restore-drill` 记录只代表小数据集，不能代替目标机演练 |
| ☐ | 对生产备份的恢复演练 | 按 [恢复](../../deploy/README.md#恢复) 在**独立空目标**执行 `deploy/backup/restore.sh environment <备份目录>` | 打印 `RESTORE OK`，退出 0 |
| ☐ | 演练后证据完整性 | 在演练/恢复目标上 `$DC run --rm --no-deps -T api easyaudit-next verify-evidence`；`... cleanup-evidence-orphans --dry-run` | `verify-evidence` 退出 0、零不一致；dry-run 的 `failed`、`refused` 为 0 |

记录：演练日期 ____；耗时 ____ s；结果 ____。

## 4. 监控

| ☐ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☐ | 健康检查（仅容器内，网关不转发 `/health/*`） | `$DC exec -T api python -c 'import urllib.request; [print(p, urllib.request.urlopen("http://127.0.0.1:8000/health/"+p, timeout=3).read().decode()) for p in ("live", "ready")]'` | `live`、`ready` 均 200，`ready` 各项 `ok`。注意 `ready` 不校验对象存储凭证和 bucket，需用一次真实 Evidence 上传/下载补验 |
| ☐ | 结构化日志可查 | `$DC logs --since 1h api`（stdout 一行一个 JSON，含 `request_id`、`route`、`status_code`、`latency_ms`）；用户报错时用响应头 `X-Request-ID` 检索 | 能看到最近请求；近 1 小时 5xx 比例 ____（无持续升高）；无 `evidence_object_missing`、`evidence_object_size_mismatch` 及其他持续出现的 ERROR |
| ☐ | auth 清理 timer | `systemctl list-timers easyaudit-cleanup-auth.timer`；`systemctl show easyaudit-cleanup-auth.service -p Result` | 已启用，最近一次 `Result=success` |
| ☐ | 证据孤儿清理 timer | `systemctl show easyaudit-cleanup-evidence-orphans.service -p Result`；首次启用前已跑过 `--dry-run` | 最近一次 `Result=success`（`failed`、`refused`、`deleted_but_registered` 均为 0） |
| ☐ | 提醒 sweep timer | `systemctl show easyaudit-reminder-sweep.service -p Result`；`journalctl -u easyaudit-reminder-sweep -n 1 --no-pager` | 最近一次 `Result=success`，JSON 的 `failed_count` 为 0 |
| ☐ | 提醒状态 | `$DC run --rm --no-deps -T api easyaudit-next scheduler-status --max-age-hours 26`；`systemctl show easyaudit-reminder-status.service -p Result` | 退出 0（最近一次成功不早于 26 小时）。sweep 至少成功一次后才启用 status timer，否则报 `never_run` |
| ☐ | 备份新鲜度 timer | `systemctl show easyaudit-backup-freshness.service -p Result` | 最近一次 `Result=success` |
| ☐ | 磁盘与对象存储余量 | 宿主机 `df -h`（Docker 数据目录、备份目录所在盘）；`docker system df -v`（postgres_data / object_data 卷） | 各盘可用 ≥ ____ %；按当前 Evidence 增长估算能支撑试点周期。仓库没有容量告警，由维护者人工查看 |
| ☐ | 失败信号有人接收 | 仓库不接外部告警；确认值守人及查看频率：____ | 已指定 |

## 5. 回滚方式

仓库没有维护模式、流量切换或自动回滚工具。详细决策表见 [升级：失败决策与回退边界](../../deploy/README.md#失败决策与回退边界)。

| ☐ | 场景 | 做法 | 选择条件 |
|---|---|---|---|
| ☐ | 应用回滚（迁移**尚未**执行） | 切回上一 release 的干净检出，`export EASYAUDIT_RELEASE=<上一 release>`，`$DC up -d --wait gateway`，再做第 4 节健康检查和登录验收 | 构建/配置失败、迁移前发现问题 |
| ☐ | 迁移已执行后的问题 | **不能**只换回旧镜像，也不要随意 `alembic downgrade`：部分 `downgrade()` 会丢表（如 0008 drop `evidences`、0013、0014），无损回退与旧应用兼容新 schema 均未建立。先 `$DC stop gateway api web` 保留数据，再选：① forward fix；② 从升级前的备份在独立目标恢复（见 [恢复](../../deploy/README.md#恢复)） | 迁移含不可逆变更或已有新写入时，只能通过恢复备份回滚；备份之后的写入不会自动合并 |
| ☐ | 升级前准备 | 升级前已有 `backup.sh` exit 0 且 `verify.sh --bundle-only` 通过的恢复点 | 恢复点目录：____ |

## 6. 停止条件

出现任一情况，立即暂停试点，由维护者决定是否恢复：

- 数据跨组织/跨权限泄漏迹象（用户看到不属于自己组织或无权限的数据）。
- 无法登录（非单个账号被限流；单账号限流用 `cleanup-auth --clear-login-name <name>` 解封）。
- 备份失败：`check-freshness.sh` 非零，或 `backup.sh` exit 1 / 3。
- 证据完整性失败：`verify-evidence` 非零，或出现 `evidence_object_missing` / `evidence_object_size_mismatch`。
- `/health/ready` 持续 503，或 5xx 持续升高。
- `scheduler-status` 持续非零（提醒不再发出）。

暂停操作（均需在已确认的 project 上执行）：

1. 由维护者手动下线入口：`$DC stop gateway api web`（保留 postgres、object-storage 与全部卷，不使用 `down -v`）。仓库没有维护页，如需通知用户由维护者自行处理。
2. 停止会写数据的 timer：`sudo systemctl stop easyaudit-reminder-sweep.timer easyaudit-cleanup-auth.timer easyaudit-cleanup-evidence-orphans.timer`；保留 `easyaudit-backup.timer`，必要时先手动跑一次 `backup.sh`。
3. 保留现场：不删卷，记录日志（`$DC logs api`）、`request_id`、`backup_timestamp`，再按第 5 节决定修复或恢复。

## 7. 试点范围确认

| ☐ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☐ | 1 个组织 | 管理员 `GET /api/v1/admin/organization` | 仅一个组织，`is_active` 为 true |
| ☐ | 2 个部门、10–20 个用户 | 管理设置 `/admin`；`GET /api/v1/admin/departments`、`/admin/users` 或界面列表 | 部门 2 个，用户 10–20 人，均已设置 primary department |
| ☐ | 两个场景已发布 | `easyaudit-next publish-scenario --organization-id <org-id> --key process_review --version 1`、`--key compliance_review --version 1`（见 [首次部署](../../deploy/README.md#首次部署到业务-ready)）；核对 `GET /api/v1/admin/scenario-status` | 两个 v1 均 published/ready；创建人的 `GET /api/v1/review-catalog` 返回 `process_review@1` 与 `compliance_review@1`。重复发布会失败，先查状态 |
| ☐ | 预期 Case 规模 | 与业务方确认 | 10–30 个 Case |
| ☐ | bootstrap 管理员已改密 | bootstrap 管理员默认**不**要求首次改密：由其本人通过界面（或 `POST /api/v1/me/password`）改密并重新登录；其他用户创建时 `must_change_password` 为 true，首次登录改密 | 初始密码已失效；初始密码未留存于任何聊天、工单或脚本 |

## 8. 签字

| 项 | 内容 |
|---|---|
| 检查人 | |
| 检查日期 | |
| 部署 release / revision | |
| 结论 | ☐ 上线　☐ 暂缓（原因：） |
| 维护者批准开放 | |
| 一周后复盘日期 | |
