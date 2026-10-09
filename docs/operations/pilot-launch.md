# 试点上线检查清单

上线前逐项勾选并签字。命令在仓库根目录执行，约定与 [部署手册](../../deploy/README.md) 一致：`DC="docker compose -f deploy/compose.yaml"`，且已 export `EASYAUDIT_RELEASE`、`COMPOSE_PROJECT_NAME`、`EASYAUDIT_SECRETS_DIR`、`EASYAUDIT_CERTS_DIR`。尖括号和 `____` 由维护者填写。

## 1. 版本

| ☑ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☑ | 部署的 release 与 main 提交对应 | `git rev-parse HEAD`；`docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$($DC ps -q api)"`（`web`、`object-storage` 同理）；`git merge-base --is-ancestor <release> origin/main` | 三个镜像 label 一致，等于 `EASYAUDIT_RELEASE` 和检出 HEAD，且该提交在 `origin/main` 上；工作区干净（`git diff --quiet HEAD`） |
| ☑ | 数据库迁移到 head | `$DC run --rm --no-deps -T migrate alembic current`；`... alembic heads` | 两者输出同一个 revision |
| ☑ | 配置与部署入口一致 | 对照 [配置参考](configuration.md)：systemd unit 与手动命令使用同一 `EASYAUDIT_RELEASE`、project、secrets/certs 路径；若维护者按配置参考「配置变更与激活」用 override 注入了 `APP_ENV` / `LOG_LEVEL`，所有后续 `$DC` 操作都带同一 override，并确认生效（base compose 不注入，`deploy/.env` 无效） | 无差异；`/health/ready` 的 `configuration`、`migrations` 为 `ok`。`APP_ENV` 保持 base compose 默认值也可接受，是否用 override 由维护者决定 |

记录：release `5a2804bda33c6d45fb34eaae970fe581c64a9f69`；revision `20261003_0014`。

## 2. 备份新鲜度

| ☑ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☑ | 最近一份 `integrity: ok` 备份的时间 | `EASYAUDIT_BACKUP_DIR=<backup-root> deploy/backup/check-freshness.sh`；`systemctl list-timers easyaudit-backup.timer easyaudit-backup-freshness.timer` | 退出 0；`backup_timestamp` 距今 ≤ 24 小时（默认 `EASYAUDIT_BACKUP_MAX_AGE_HOURS=24`） |
| ☑ | 最近一次备份 service 成功 | `systemctl show easyaudit-backup.service -p Result -p ExecMainStatus`；`journalctl -u easyaudit-backup.service -n 50 --no-pager` | `Result=success`；不是 exit 3（degraded） |
| ☑ | 位置与大小 | `ls -ld <backup-root>`；`du -sh <backup-root>/easyaudit-backup-*` | 备份目录权限 0700、与数据卷不在同一块盘；最新包大小与前几份同量级（不为空、不骤降），数值 200K |
| ☑ | 备份包自身完整 | `deploy/backup/verify.sh <最新备份目录> --bundle-only` | 退出 0；`manifest.json` 的 `release_sha` / `alembic_revision` 与第 1 节一致或可解释 |

## 3. 恢复演练

| ☑ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☑ | 在目标机器、按实际数据量做过一次演练 | 在专用可丢弃 Docker 主机运行 `deploy/backup/drill.sh`（固定 project `easyaudit-drill`，会 `down -v`，绝不能在生产主机运行）；记录 `restore-drill-record.json`（`result`、`actual_rto_seconds`、`backup_timestamp`、`release_sha`） | `result` 通过；`actual_rto_seconds` ≤ `DRILL_RTO_LIMIT_SECONDS`（默认 14400，设计目标 RTO ≤ 4h）；演练使用的 release 即本次上线 release。CI 的 `backup-restore-drill` 记录只代表小数据集，不能代替目标机演练 |
| ☑ | 对生产备份的恢复演练 | 按 [恢复](../../deploy/README.md#恢复) 在**独立空目标**执行 `deploy/backup/restore.sh environment <备份目录>` | 打印 `RESTORE OK`，退出 0 |
| ☑ | 演练后证据完整性 | 在演练/恢复目标上 `$DC run --rm --no-deps -T api easyaudit-next verify-evidence`；`... cleanup-evidence-orphans --dry-run` | `verify-evidence` 退出 0、零不一致；dry-run 的 `failed` 为 0，`refused` 为 0 或 null（未触发时为 null） |

记录：演练日期 2026-10-09；耗时 24 s；结果 通过。

## 4. 监控

| ☑ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☑ | 健康检查（仅容器内，网关不转发 `/health/*`） | `$DC exec -T api python -c 'import urllib.request; [print(p, urllib.request.urlopen("http://127.0.0.1:8000/health/"+p, timeout=3).read().decode()) for p in ("live", "ready")]'` | `live`、`ready` 均 200，`ready` 各项 `ok`。注意 `ready` 不校验对象存储凭证和 bucket，需用一次真实 Evidence 上传/下载补验 |
| ☑ | 结构化日志可查 | `$DC logs --since 1h api`（stdout 一行一个 JSON，含 `request_id`、`route`、`status_code`、`latency_ms`）；用户报错时用响应头 `X-Request-ID` 检索 | 能看到最近请求；近 1 小时 5xx 比例 0%（无持续升高）；无 `evidence_object_missing`、`evidence_object_size_mismatch` 及其他持续出现的 ERROR |
| ☑ | auth 清理 timer | `systemctl list-timers easyaudit-cleanup-auth.timer`；`systemctl show easyaudit-cleanup-auth.service -p Result` | 已启用，最近一次 `Result=success` |
| ☑ | 证据孤儿清理 timer | `systemctl show easyaudit-cleanup-evidence-orphans.service -p Result`；首次启用前已跑过 `--dry-run` | 最近一次 `Result=success`（JSON 里 `failed`、`deleted_but_registered` 为 0，`refused` 为 0 或 null） |
| ☑ | 提醒 sweep timer | `systemctl show easyaudit-reminder-sweep.service -p Result`；`journalctl -u easyaudit-reminder-sweep -n 20 --no-pager`（最后一行常是 systemd 的 `Finished`/`Deactivated`，找最后一条 JSON 行） | 最近一次 `Result=success`，JSON 的 `failed_count` 为 0 |
| ☑ | 提醒状态 | `$DC run --rm --no-deps -T api easyaudit-next scheduler-status --max-age-hours 26`；`systemctl show easyaudit-reminder-status.service -p Result` | 退出 0（最近一次成功不早于 26 小时）。sweep 至少成功一次后才启用 status timer，否则报 `never_run` |
| ☑ | 备份新鲜度 timer | `systemctl show easyaudit-backup-freshness.service -p Result` | 最近一次 `Result=success` |
| ☑ | 磁盘与对象存储余量 | 宿主机 `df -h`（Docker 数据目录、备份目录所在盘）；`docker system df -v`（postgres_data / object_data 卷） | 各盘可用 ≥ 58%（当前剩余 17GB，使用率 41%）；按当前 Evidence 增长估算能支撑试点周期。仓库没有容量告警，由维护者人工查看 |
| ☑ | 失败信号有人接收 | 仓库不接外部告警；确认值守人及查看频率：系统管理员(每日早晚巡检) | 已指定 |

## 5. 回滚方式

仓库没有维护模式、流量切换或自动回滚工具。详细决策表见 [升级：失败决策与回退边界](../../deploy/README.md#失败决策与回退边界)。

| ☑ | 场景 | 做法 | 选择条件 |
|---|---|---|---|
| ☑ | 应用回滚（迁移**尚未**执行） | 切回上一 release 的干净检出，`export EASYAUDIT_RELEASE=<上一 release>`，`$DC up -d --wait gateway`，再做第 4 节健康检查和登录验收 | 构建/配置失败、迁移前发现问题 |
| ☑ | 迁移已执行后的问题 | **不能**只换回旧镜像，也不要随意 `alembic downgrade`：部分 `downgrade()` 会丢表（如 0008 drop `evidences`、0013、0014），无损回退与旧应用兼容新 schema 均未建立。先 `$DC stop gateway api web` 保留数据，再选：① forward fix；② 从升级前的备份在独立目标恢复（见 [恢复](../../deploy/README.md#恢复)） | 迁移含不可逆变更或已有新写入时，只能通过恢复备份回滚；备份之后的写入不会自动合并 |
| ☑ | 升级前准备 | 升级前已有 `backup.sh` exit 0 且 `verify.sh --bundle-only` 通过的恢复点 | 恢复点目录：/home/zexiong/easyaudit_local/backups/easyaudit-backup-20261009T004903Z |

## 6. 停止条件

出现任一情况，立即暂停试点，由维护者决定是否恢复：

- 数据跨组织/跨权限泄漏迹象（用户看到不属于自己组织或无权限的数据）。
- 无法登录（非单个账号被限流；单账号限流用 `cleanup-auth --clear-login-name <name>` 解封）。
- 备份失败：`check-freshness.sh` 非零，或 `backup.sh` exit 1 / 3。
- 证据完整性失败：`verify-evidence` 非零，或出现 `evidence_object_missing` / `evidence_object_size_mismatch`。
- `/health/ready` 持续 503，或 5xx 持续升高。
- `scheduler-status` 持续非零（提醒不再发出）。

暂停操作（均需在已确认的 project 上执行）。`backup.sh` 要求 postgres、object-storage、api、web、gateway 都在运行，所以"先备份"与"先下线"不能同时满足，按停止条件类型选顺序：

**A. 数据跨组织/跨权限泄漏迹象：先下线入口，不等备份**

1. 立即由维护者手动下线入口：`$DC stop gateway api web`（保留 postgres、object-storage 与全部卷，不使用 `down -v`）。仓库没有维护页，如需通知用户由维护者自行处理。
2. 停所有 timer：`sudo systemctl stop easyaudit-reminder-sweep.timer easyaudit-cleanup-auth.timer easyaudit-cleanup-evidence-orphans.timer easyaudit-backup.timer easyaudit-backup-freshness.timer`。
3. 保留现场：记录日志（`$DC logs api`）、`request_id`、最近一份备份的 `backup_timestamp`。需要留存现场数据时，不在停机状态下跑 `backup.sh`（会 exit 1）；已有最近备份可用，或在维护者确认后恢复服务再备份，或用备份在独立目标恢复后调查。

**B. 其他停止条件（备份失败、完整性失败、5xx、无法登录等）：先停 timer、留存备份，再下线**

1. 停写数据的 timer：`sudo systemctl stop easyaudit-reminder-sweep.timer easyaudit-cleanup-auth.timer easyaudit-cleanup-evidence-orphans.timer`；确认没有正在运行的 oneshot：`systemctl list-units --type=service --state=running 'easyaudit-*'`。
2. 如需留存现场备份（不适用于备份本身故障的情形）：在五个服务仍运行时跑 `deploy/backup/backup.sh`，确认 exit 0 且 `verify.sh <目录> --bundle-only` 通过；exit 1 或 3 不算有效留存，按失败处理，不要为此无限期推迟下线。
3. `$DC stop gateway api web` 下线入口，同时 `sudo systemctl stop easyaudit-backup.timer easyaudit-backup-freshness.timer`（停机期间 backup 会 exit 1、freshness 会误报）。
4. 记录日志与 `request_id`，再按第 5 节决定修复或恢复。

恢复试点时：`$DC up -d --wait gateway`，通过第 4 节健康检查和登录验收后，再 `sudo systemctl start` 上面停掉的 timer，并用 `systemctl list-timers` 核对。

## 7. 试点范围确认

| ☑ | 检查 | 怎么确认 | 通过标准 |
|---|---|---|---|
| ☑ | 1 个组织 | 管理员 `GET /api/v1/admin/organization` | 仅一个组织，`is_active` 为 true |
| ☑ | 2 个部门、10–20 个用户 | 管理设置 `/admin`；`GET /api/v1/admin/departments`、`/admin/users` 或界面列表 | 部门 2 个，用户 10–20 人，均已设置 primary department |
| ☑ | 两个场景已发布 | `easyaudit-next publish-scenario --organization-id <org-id> --key process_review --version 1`、`--key compliance_review --version 1`（见 [首次部署](../../deploy/README.md#首次部署到业务-ready)）；核对 `GET /api/v1/admin/scenario-status` | 两个 v1 均 published/ready；创建人的 `GET /api/v1/review-catalog` 返回 `process_review@1` 与 `compliance_review@1`。重复发布会失败，先查状态 |
| ☑ | 预期 Case 规模 | 与业务方确认 | 10–30 个 Case |
| ☑ | bootstrap 管理员已改密 | bootstrap 管理员默认不要求首次改密，界面也没有个人改密入口。密码由管理员本人在 `bootstrap-admin` 的 CLI 提示中输入、未经他人之手：无需改密。若由他人代为执行 bootstrap：管理员登录后在 `/admin`「临时凭据重置」选择自己设临时密码（也可调 `POST /api/v1/admin/users/{user_id}/credential-reset`；服务端不禁止重置自己，会撤销其 Session），重新登录后在强制改密页改密（或 `POST /api/v1/me/password`）。其他用户创建时 `must_change_password` 为 true，首次登录改密 | bootstrap 密码仅管理员本人知晓，或代执行时的初始密码已失效；初始/临时密码未留存于任何聊天、工单或脚本 |

## 8. 签字

| 项 | 内容 |
|---|---|
| 检查人 | 系统管理员 |
| 检查日期 | 2026-10-09 |
| 部署 release / revision | 5a2804bda33c6d45fb34eaae970fe581c64a9f69 / 20261003_0014 |
| 结论 | ☑ 上线　☐ 暂缓（原因：） |
| 维护者批准开放 | 批准上线 (Pilot Go-live Ready) |
| 一周后复盘日期 | 2026-10-16 |
