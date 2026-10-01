# 生产部署（私有网络）

```text
Private Network → gateway (Caddy, 仅 :443) → { web (nginx, SPA), api (FastAPI) }
                                               api → { postgres, object-storage (Garage, S3) }
```

- 只有 `gateway` 发布端口，且只有 443（无 80，不做 HTTP 跳转）。
- 除 gateway 外没有任何宿主机端口发布；`backend` 网络是 `internal: true`，禁止容器外联。注意 `internal` 并不阻止 Linux 宿主机直接访问容器 IP，宿主机本身应视为可信，并靠宿主机防火墙限制访问。
- 所有容器以非 root 运行，所有镜像固定到具体版本（`tests/unit/test_deploy_compose.py` 强制）。
- 开发用的根目录 `compose.yaml` 与本目录无关，不要混用。

以下命令都在仓库根目录执行，`DC="docker compose -f deploy/compose.yaml"`。**每条 compose 命令都需要 `EASYAUDIT_RELEASE`**（没有默认值）：自建镜像用它打 tag（`easyaudit/api:<sha>`），并写入 OCI label `org.opencontainers.image.revision`，这样运行中的容器能对应到具体的 release。

```bash
export EASYAUDIT_RELEASE=$(git rev-parse HEAD)
```

## 1. 准备 secrets 和证书（不提交）

```bash
install -d -m 700 deploy/secrets deploy/certs
openssl rand -hex 24 | tr -d '\n' > deploy/secrets/postgres_password
openssl rand -hex 32 | tr -d '\n' > deploy/secrets/garage_rpc_secret
printf 'GK%s' "$(openssl rand -hex 12)" > deploy/secrets/s3_access_key_id   # 必须是 GK + 24 位十六进制
openssl rand -hex 32 | tr -d '\n' > deploy/secrets/s3_secret_access_key      # 64 位十六进制
chmod 444 deploy/secrets/*
```

容器以非 root uid 读取这些文件，所以文件本身为 0444，靠 `deploy/secrets`、`deploy/certs` 目录 0700 限制宿主机上的其他用户（compose 按文件挂载 secrets，所以父目录不需要对容器可读）。**不要**把这两个目录放宽，也不要把私钥单独设成 0444 放在可遍历目录里。`deploy/secrets/`、`deploy/certs/`、`deploy/.env` 已在 `.gitignore` 中。

**TLS 证书**：网关以 Docker secrets 方式读取 `deploy/certs/tls.crt`（含中间证书链）和 `tls.key`。网关 uid 是 10002，读不了运维用户 0600 的文件，所以 CA 给的文件要复制成 0444（目录 0700 已保护）：`install -m 444 <ca-issued.key> deploy/certs/tls.key`，证书同理。也可以在有 root 的情况下改用 `chgrp 10002` 加 0440。会话 Cookie 是 `__Host-` 前缀且 Secure，浏览器必须通过 HTTPS 访问，且证书对访问所用的主机名有效。

- 内部 CA：让 CA 为服务的内网域名签发证书，放入上述文件；客户端需信任该 CA。
- 自签（仅试用）：

  ```bash
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=easyaudit.internal" \
    -addext "subjectAltName=DNS:easyaudit.internal" \
    -keyout deploy/certs/tls.key -out deploy/certs/tls.crt
  chmod 444 deploy/certs/*   # 目录为 0700，见上
  ```

  然后把 `tls.crt` 分发给客户端并加入信任。

可通过 `deploy/.env`（模板 `deploy/.env.example`）改变 secrets/证书目录。

## 2. 初始化顺序

```bash
$DC build
$DC up -d --wait postgres object-storage      # object-storage 就绪即表示 bucket 与密钥已创建
$DC run --rm migrate                          # 显式迁移，API 启动时不会自动迁移
$DC up -d --wait gateway                      # 同时拉起 api、web
$DC run --rm api easyaudit-next bootstrap-admin \
  --organization-name "<组织名>" --admin-name "<管理员姓名>" --login-name "<登录名>"
```

`bootstrap-admin` 会交互式询问密码（需要 TTY），仅在尚无组织时可用。之后通过 `https://<域名>/` 登录。

## 升级

`git pull` → `export EASYAUDIT_RELEASE=$(git rev-parse HEAD)` → `$DC build` → `$DC run --rm migrate` → `$DC up -d`。迁移始终在新 API 启动前手动执行。升级要一次做完：`git pull` 之后、`up -d` 之前，备份会因"运行中的镜像与检出版本不一致"而拒绝执行。

## 认证维护

`$DC run --rm --no-deps -T api easyaudit-next cleanup-auth` 删除过期的 `login_throttle` 窗口（运维计数，不是业务数据），向 stdout 输出一行 JSON：删除条数和已过期 Session 的计数。**不删除也不修改任何 Session**：`auth_sessions` 是审计事件的 FK 锚点，试点期只增不删，过期靠 `expires_at` 保证不可用。某个登录名被限流误封（或被他人故意封锁）时，运维用 `$DC run --rm --no-deps -T api easyaudit-next cleanup-auth --clear-login-name <name>` 立即解封（名字会按登录规则规范化；输出里 `login_name_cleared` 是删除的窗口数）。`deploy/easyaudit-cleanup-auth.service/.timer` 是每天一次的 systemd 示例（安装方式同备份）。

## 备份

目标：RPO ≤ 24h，RTO ≤ 4h。工具在 `deploy/backup/`，全部通过一次性容器（`db-tool`、`object-tool`，只接入 `backend` 网络，不发布端口，非 root，`cap_drop: ALL`）访问数据库和对象存储。前置条件：docker compose、python3、flock，且用**非 root** 的运维账号（在 docker 组内，且拥有 0700 的 `deploy/secrets`）执行，容器以该账号的 uid 写备份目录。

```bash
export EASYAUDIT_RELEASE=$(git rev-parse HEAD)
EASYAUDIT_BACKUP_DIR=/srv/easyaudit-backups deploy/backup/backup.sh
```

- 备份目录**权限必须是 0700**（脚本会检查，不满足就拒绝）。每次备份生成 `easyaudit-backup-<UTC 时间戳>/`，内含 `database.dump`（`pg_dump -Fc`）、`objects/`（bucket 的 S3 镜像，用固定版本的 rclone 经 S3 协议拷贝，不依赖 Garage 内部卷）和 `manifest.json`。备份先写到 `.partial` 目录，成功后才改名，因此看到的完整目录一定是成功的备份。
- **一致性**：先 `pg_dump`，再镜像对象。对象由服务端生成 key、只写一次、不覆盖（Pilot-4 遵守），所以 dump 之后拷贝的对象集合一定是 DB 引用集合的超集。多出来的是孤儿对象，由 Pilot-4B 的孤儿清理处理。备份时会核对 dump 里 Evidence 引用的对象：key 在存储里**不存在**，或 size/sha256 与对象**不一致**，都算完整性问题。备份**照常完成并保留**（不能因为个别坏数据让 RPO 失守），manifest 记 `"integrity": "degraded"` 并列出 `integrity_problems`，脚本以**退出码 3**结束（普通失败是 1，成功是 0），systemd 会显示 failed，运维能发现。`verify` 对 degraded 备份判失败；`restore` 允许恢复 degraded 备份，但开始前会醒目打印问题清单。
- **manifest**：`backup_timestamp`（UTC，dump 开始时刻）、`release_sha`（读运行中 api 镜像的 revision label，不信任环境变量；api/web/object-storage 三个镜像的 label 必须一致且等于当前检出）、`alembic_revision`（取自 dump 内的 `alembic_version`）、dump 的 sha256、每个对象的 key/size/sha256、各服务的镜像 tag、开始时间与耗时。
- **保留策略**：默认保留 14 天，`EASYAUDIT_BACKUP_RETENTION_DAYS` 可改。新备份成功之后才清理过期备份。degraded 备份照常按天数过期，但**最近一份 `integrity: ok` 的备份永远不删**（否则对象持续缺失时，14 天后会把最后一份健康备份清掉）；过期的陈旧 `.partial` 会清理，名字不符合 `easyaudit-backup-<时间戳>` 格式的目录不会被碰。
- **退出码**：`backup.sh` 0=成功；1=失败、没有产出备份；3=备份已产出但完整性 degraded（见上）。timer 对非零都会显示 failed，需要处理 degraded 时看备份里的 `manifest.json`。
- **调度与 RPO**：`easyaudit-backup.service` / `easyaudit-backup.timer` 是 systemd 示例，**每 12 小时一次**（02:30、14:30，无随机延迟），这样一次备份失败后，上一份备份仍不超过 24h。仅靠调度并不能保证 RPO：用 `deploy/backup/check-freshness.sh`（`EASYAUDIT_BACKUP_DIR`、`EASYAUDIT_BACKUP_MAX_AGE_HOURS`，默认 24）做监控，最近一份 `integrity: ok` 备份的 `backup_timestamp` 早于 24h 就以非零退出（degraded 和 `.partial` 不算）。`easyaudit-backup-freshness.service/.timer` 是每小时执行它的示例；Pilot-7 上线检查清单的"备份新鲜度"就用它。安装：改路径和账号后 `systemctl enable --now easyaudit-backup.timer easyaudit-backup-freshness.timer`。
- **不进备份包**：secrets 和 TLS 证书。新环境生成新的即可，用户密码哈希在数据库里，不受影响；TLS 证书由运维单独保管。

### 已知限制

- **和数据在同一块盘上的备份不算备份。** 备份目录必须在另一块盘或另一台机器上；异地拷贝由运维负责，本仓库不做异地同步。
- 备份包未加密，只靠目录 0700 保护，包含全部业务数据和证据文件。加密与异地同步不在 Pilot-1B 范围内。
- 备份在线进行，不停服务：DB 是 `pg_dump` 的一致快照，对象是 dump 之后的镜像（见上文）。
- 恢复演练的 RTO 是在小数据量、CI 镜像缓存较热的条件下测得的下限；真实 RTO 主要由数据量、镜像构建/拉取和磁盘速度决定，上线前应在目标机器上按实际数据量再演练一次。

## 恢复

恢复**只写入空目标**：数据库里已有表，或 bucket 非空，一律拒绝，没有 `--force`。要恢复就用全新的环境（`down -v`）。

```bash
deploy/backup/verify.sh BACKUP_DIR                 # 备份包自检，加 --bundle-only 则只查备份包
deploy/backup/restore.sh database    BACKUP_DIR    # pg_restore 到空库
deploy/backup/restore.sh objects     BACKUP_DIR    # 对象拷回空 bucket
deploy/backup/restore.sh environment BACKUP_DIR    # 整个新环境，见下
```

`restore.sh environment` 的步骤：

1. 检查 manifest 的 `release_sha` 等于当前检出的 HEAD 和 `EASYAUDIT_RELEASE`（且无未提交改动），不一致就拒绝，并提示 `git checkout <sha>`。这个检查对 `database`、`objects`、`environment` 三个入口都是第一步，写入之前完成；目标上已有 api 容器时，还要核对它镜像 label 里的 revision。
2. 用**新的** secrets 和证书（按第 1 节准备好）构建镜像，起 postgres 和 object-storage，然后**同时检查数据库和 bucket 都为空**，任何一个非空都拒绝，此时还没有写入任何东西。
3. 恢复数据库，恢复对象。
4. 校验 `alembic current` 等于 manifest 的 revision，并且等于该 release 的 head；否则不启动应用。
5. 启动 api、web、gateway，并运行 `verify.sh`。

`verify.sh` 做三件事：重新计算每个对象的 sha256 并与 manifest 比对；检查数据库里每条 Evidence 的 storage_key 对应对象存在，且 sha256、size 一致；列出全部不一致，有任何不一致就以非零状态退出。恢复后的检查和平时的故障诊断都用它。

### 恢复演练

`deploy/backup/drill.sh` 走完整流程：临时证书和 secrets 部署 → migrate、`bootstrap-admin`（用 stdin 传密码，`getpass` 在没有 TTY 时读 stdin）→ 通过网关的真实 API 建 ReviewPlan、Case、Finding、Action，并**上传三个真实文件**作为 Evidence（最大的一个 9 MiB，超过 8 MiB 的 part 大小，走多段上传；服务端算出的 size/sha256 必须与本地一致），再从 bucket 读回对象，确认 bucket 里恰好是这三个对象且 sha256 一致 → `backup.sh` → `down -v` → 生成新 secrets 和证书 → `restore.sh environment` → 验证（`alembic current` 等于 head、原账号登录、打开原 Case 和 Finding、Evidence 元数据、`verify.sh`），并确认恢复会拒绝非空目标，以及 release 不匹配（`database`、`objects`、`environment` 三个入口都测）；最后故意删掉一个已登记的对象再备份，断言退出码为 3、备份被保留、manifest 标记 degraded、`verify` 判失败，`check-freshness.sh` 只认更早那份 ok 备份；再拆掉环境、往 bucket 里放一个对象，断言 `restore.sh environment` 在写数据库之前就拒绝、数据库保持为空。实际 RTO 超过 `DRILL_RTO_LIMIT_SECONDS`（默认 14400）演练判失败；记录写不进去也判失败。输出 `restore-drill-record.json`（`restore_started_at`、`restore_completed_at`、`actual_rto_seconds`、`backup_timestamp`、`release_sha`、`result`）。CI 对应 `backup-restore-drill` job（不是 required check），记录作为 artifact 上传并打印在日志里。

"通过 API 下载 Evidence"要等 Pilot-4B 的下载端点；`drill_api.py` 的 `check` 里留了扩展点，Pilot-4B 必须把它加进演练。在此之前用对象级 sha256 校验代替。

## 冒烟测试

`deploy/smoke.sh` 用临时证书和 secrets 完整跑一遍（build → 镜像 label → migrate → up → HTTPS 验证 → API `ready` 含 `object_storage: ok` → 未认证上传 401、超过网关上限的上传 413 → 无非网关端口发布 → down -v）。前置条件：docker compose、git、openssl、curl、python3。本机 443 被占用时设置 `EASYAUDIT_HTTPS_PORT`。CI 中对应 `deploy-smoke` job。

## 说明

- 对象存储为 Garage（单节点）。API 用 `s3_access_key_id`/`s3_secret_access_key` 访问 bucket `easyaudit-evidence`（内部端点 `http://object-storage:3900`，region `garage`），凭证以 secrets 文件挂载，环境变量只给文件路径（`OBJECT_STORAGE_*_FILE`）。API 的 `/health/ready` 含 `object_storage`（HeadBucket）；`up --wait gateway` 等的就是它，所以凭证或 bucket 不对时 API 起不来。
- Evidence 上传限制由 `EVIDENCE_MAX_BYTES`（默认 25 MiB）和 `EVIDENCE_ALLOWED_CONTENT_TYPES` 控制。网关的 `request_body max_size`（`Caddyfile`，26 MiB）要略大于应用上限：调大应用上限时同步改它。
- 上传失败后可能留下孤儿对象（登记失败且删除也失败）或未完成的 multipart（进程崩溃）；它们不在任何 Evidence 行里引用，备份会把前者当作多出来的对象带走，清理由 Pilot-4B 的孤儿清理处理。
- API 只信任来自网关固定地址（`172.30.10.10`）的代理头。若该网段与内网冲突，同时修改 `compose.yaml` 中 `edge` 网段、网关 `ipv4_address` 和 `FORWARDED_ALLOW_IPS`（测试会检查后两项一致）。
