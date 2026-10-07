# 私网部署与运行操作

本页是部署、首次业务初始化、升级/失败决策、备份和恢复的 canonical procedure。使用范围为开发和经维护者批准的受控私网试点，见 [SECURITY.md](../SECURITY.md)。工具存在或 CI 演练通过不代表目标机器具备生产资格；一般生产支持、目标机 RPO/RTO 达标及外部告警交付均未由仓库证据建立。

```text
Private Network → gateway (Caddy, 仅 :443) → { web (nginx, SPA), api (FastAPI) }
                                               api → { postgres, object-storage (Garage, S3) }
```

- 只有 `gateway` 发布端口，且只有 443（无 80，不做 HTTP 跳转）。
- 除 gateway 外没有任何宿主机端口发布；`backend` 网络是 `internal: true`，禁止容器外联。注意 `internal` 并不阻止 Linux 宿主机直接访问容器 IP，宿主机本身应视为可信，并靠宿主机防火墙限制访问。
- 所有容器以非 root 运行，所有镜像固定到具体版本（`tests/unit/test_deploy_compose.py` 强制）。
- 开发用的根目录 `compose.yaml` 与本目录无关，不要混用。

## 命令环境与身份

使用 Linux 上拥有 Docker 权限的非 root 运维账号。下列命令在仓库根目录执行；每条失败就停在该阶段，不把失败后的步骤继续执行。**每条 compose 命令都需要 `EASYAUDIT_RELEASE`**（没有默认值），自建镜像用它打 tag 并写入 OCI label `org.opencontainers.image.revision`。

先人工记录并确认 Docker 主机/daemon/context、Compose project、checkout、数据卷、secret/cert 目录和备份目录的身份。以下默认 project 仅用于已经确认的首次新部署或对应 source；恢复章节使用另一台独立主机上的独立 target。开发根目录 `compose.yaml` 不可混入。

```bash
DC="docker compose -f deploy/compose.yaml"
export EASYAUDIT_RELEASE="$(git rev-parse HEAD)"
export COMPOSE_PROJECT_NAME=easyaudit
export EASYAUDIT_SECRETS_DIR="$PWD/deploy/secrets"
export EASYAUDIT_CERTS_DIR="$PWD/deploy/certs"
docker context show
$DC ps -a
$DC config --volumes
docker volume ls --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME"
```

检查 `DOCKER_HOST` / `DOCKER_CONTEXT` 是否重定向到另一 daemon；`config --volumes` 仅列卷逻辑名，还需确认实际 project 标签与容器 Mounts。配置来源、37 项 Settings、生效/recreate 和 PostgreSQL/Garage/TLS 凭证边界只在 [配置参考](../docs/operations/configuration.md)。脚本不会 source `deploy/.env`：目录和脚本输入在 Shell/unit 明确 export；不要以 `.env` 修改代表容器已经更新。

## 1. 准备 secrets 和证书（不提交）

本节的生成/安装只适用于**操作者已确认的新部署/独立空恢复目标**。先确认上述目录属于该目标且文件尚不存在；命令会写入这些文件，不可对现有 source 重跑来“轮换”。既有凭证变更使用配置参考的维护边界，不能删除数据卷重建密码。

```bash
install -d -m 700 "$EASYAUDIT_SECRETS_DIR" "$EASYAUDIT_CERTS_DIR"
openssl rand -hex 24 | tr -d '\n' > "$EASYAUDIT_SECRETS_DIR/postgres_password"
openssl rand -hex 32 | tr -d '\n' > "$EASYAUDIT_SECRETS_DIR/garage_rpc_secret"
printf 'GK%s' "$(openssl rand -hex 12)" > "$EASYAUDIT_SECRETS_DIR/s3_access_key_id"
openssl rand -hex 32 | tr -d '\n' > "$EASYAUDIT_SECRETS_DIR/s3_secret_access_key"
chmod 444 "$EASYAUDIT_SECRETS_DIR"/*
```

S3 key ID 为 `GK` + 24 位 hex；secret 为 64 位 hex。这是初始生成格式，不是既有服务端 credential 的轮换命令。

容器以非 root uid 读取这些文件，所以文件本身为 0444，靠 `deploy/secrets`、`deploy/certs` 目录 0700 限制宿主机上的其他用户（compose 按文件挂载 secrets，所以父目录不需要对容器可读）。**不要**把这两个目录放宽，也不要把私钥单独设成 0444 放在可遍历目录里。`deploy/secrets/`、`deploy/certs/`、`deploy/.env` 已在 `.gitignore` 中。

**TLS 证书**：网关按 secret 文件读取 `$EASYAUDIT_CERTS_DIR/tls.crt`（含中间链）和 `tls.key`。网关 uid 是 10002，读不了运维用户 0600 文件，所以 CA 给的文件复制为 0444（父目录 0700）：`install -m 444 <ca-issued.key> "$EASYAUDIT_CERTS_DIR/tls.key"`，证书同理。也可以在有 root 的情况下使用 gid 10002 与 0440。会话 Cookie 是 `__Host-` 前缀且 Secure，浏览器必须通过 HTTPS 访问，证书须对访问域名有效。

- 内部 CA：让 CA 为服务的内网域名签发证书，放入上述文件；客户端需信任该 CA。
- 自签（仅试用）：

  ```bash
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=easyaudit.internal" \
    -addext "subjectAltName=DNS:easyaudit.internal" \
    -keyout "$EASYAUDIT_CERTS_DIR/tls.key" -out "$EASYAUDIT_CERTS_DIR/tls.crt"
  chmod 444 "$EASYAUDIT_CERTS_DIR"/*   # 仅已确认的新目标，目录为 0700
  ```

  然后把 `tls.crt` 分发给客户端并加入信任。

可通过 `deploy/.env`（模板 `deploy/.env.example`）改变 secrets/证书目录。

## 首次部署到业务 Ready

仅在已核对为空的**首次部署**运行初始化；已有数据使用升级章节，不重复 bootstrap 或直接写数据库。

```bash
$DC build
$DC up -d --wait postgres object-storage      # object-storage 就绪即表示 bucket 与密钥已创建
$DC run --rm migrate                          # 显式迁移，API 启动时不会自动迁移
$DC up -d --wait gateway                      # 同时拉起 api、web
$DC run --rm api easyaudit-next bootstrap-admin \
  --organization-name "<组织名>" --admin-name "<管理员姓名>" --login-name "<登录名>"
```

`bootstrap-admin` 会交互式询问密码（需要 TTY），仅在尚无组织时可用。之后通过 `https://<域名>/` 登录。

### 从基础设施 Ready 到可创建业务

1. **内部健康检查**：health router 不在 `/api/v1` 下，gateway 不转发 `/health/*`；不能把网关上的 SPA 响应当成健康结果。在已确认 project 执行：

   ```bash
   $DC exec -T api python -c 'import urllib.request; [print(p, urllib.request.urlopen("http://127.0.0.1:8000/health/"+p, timeout=3).read().decode()) for p in ("live", "ready")]'
   ```

   live=200/status ok 只证明进程；ready=200 且 checks 全 ok 证明当前配置/数据库连通/revision/对象 endpoint 可达。ready 的 unsigned HEAD **不证明 S3 凭证或 bucket 授权正确**；后者还需真实 Evidence 上传/下载验证。

2. **管理员认证并取得组织 ID**：通过受信任 HTTPS 登录。已登录浏览器同源访问 `GET /api/v1/me`，取 `organization_id`；也可用管理员的 `GET /api/v1/admin/organization` 核对 `id/name/is_active`。bootstrap 本身不输出 org-id，仓库没有“查询组织 ID”的 CLI。可在已登录浏览器开发者控制台执行只读请求：

   ```javascript
   const meResponse = await fetch('/api/v1/me', { credentials: 'same-origin' });
   if (!meResponse.ok) throw new Error(`me: ${meResponse.status}`);
   const me = await meResponse.json();
   console.log({ organization_id: me.organization_id, must_change_password: me.must_change_password });
   ```

3. **为该组织发布两个精确 v1 场景**：以下 UUID 用上一步真实结果替换；执行者是有该数据库访问权的运维账号，CLI 不经过 HTTP 登录。

   ```bash
   ORG_ID='<上一步确认的 organization_id UUID>'
   $DC run --rm --no-deps -T api easyaudit-next publish-scenario --organization-id "$ORG_ID" --key process_review --version 1
   $DC run --rm --no-deps -T api easyaudit-next publish-scenario --organization-id "$ORG_ID" --key compliance_review --version 1
   ```

   组织必须存在，版本必须在当前代码 registry。已发布的同 key/version 再发布会失败，先查管理员 `GET /api/v1/admin/scenario-status` / `GET /api/v1/admin/scenarios/{key}/versions`，不要把重复发布错误当部署损坏。

4. **部门/用户与首次改密**：管理员打开“管理设置” `/admin`，建立所需部门，再创建用户并设置 primary department；对应公开 API 是 `POST /api/v1/admin/departments`（name、可选 parent_id）和 `POST /api/v1/admin/users`（display_name、login_name、initial_password、可选 primary_department_id/platform_role/must_change_password）。platform_role 是 `ordinary_user` 或 `system_admin`，不是 Lead/Auditor 等资源角色。初始密码至少 12 字符且通过服务端密码策略。UI 创建用户设 must_change_password=true；用户首次登录进入改密，`POST /api/v1/me/password` 使用 current_password/new_password。改密后按页面要求重新登录；在改密前读取业务 catalog 会是 403。bootstrap 管理员 credential 默认不要求首次改密，不能把它和临时密码用户混为一谈。

5. **核对业务 catalog**：以实际创建人的账号登录；`GET /api/v1/review-catalog` 返回该人可创建的精确场景版本，应看到 `process_review@1` 和 `compliance_review@1`（scenario_key/scenario_version/display_name）。管理员 scenario-status 中 published/registry-present/ready 不能代替创建人的 catalog 授权结果。401 先认证；403 先检查首次改密/用户状态；空 catalog 检查组织 ID、publication、active 与当前 registry，不能手工补表。

6. **创建首个 Plan → Case**：打开 `/review-plans/new`，填写计划标题、可选起止时间并保存；记录返回 Plan 的 `id`。向导随后进入 `/review-plans/<plan-id>/review-cases/new`，选择 catalog 中发布的精确版本并填写标题与场景字段。过程审查需要 area_code/review_type；合规审查需要 standard_reference/scope_summary。保存后打开 `/review-cases/<case-id>`，核对 plan_id、scenario_key、scenario_version 和 draft 状态。用同一已存在 Plan 的向导入口再验证另一个 v1 场景。

   API 等价输入供对照（用真实 Plan UUID 与当前人有权创建的版本）：

   ```json
   {"title":"首次业务验收"}
   ```

   上述为 `POST /api/v1/review-plans`；返回 201 后，`POST /api/v1/review-cases` 输入为：

   ```json
   {"plan_id":"<返回的 Plan UUID>","title":"过程审查验收","scenario_key":"process_review","scenario_version":1,"scenario_data":{"area_code":"area-a","review_type":"standard"}}
   ```

   合规 Case 换为 `compliance_review`、version=1、`scenario_data={"standard_reference":"standard-a","scope_summary":"pilot scope"}`。创建请求结果未知时先确认服务器结果；UI 重试沿用原幂等键，自制 API 客户端应为每次逻辑创建保存一个有效 `Idempotency-Key`，重试保持同键同 payload，不盲目新建第二份。

**Business-ready 最小验收**：内部 live/ready 均成功、管理员能认证、组织两场景都已发布、创建人的 catalog 返回二者、Plan 与两个精确版本的 Case 能创建并可读取其 ID/关联/version。containers healthy 只覆盖基础设施，不能代替这份验收。实际业务使用存储时，还需对应权限下真实 Evidence 上传、下载和完整性检查；本段不声称已经完成目标机现场验收。

证据：[CLI](../src/easyaudit_next/cli.py)、[catalog/创建 Router](../src/easyaudit_next/api/review_planning.py)、[管理/认证 Router](../src/easyaudit_next/api/router.py)、[clean initialization tests](../tests/integration/test_m5_5_clean_initialization.py)、[两场景 readiness tests](../tests/integration/test_m5_1_scenario_readiness.py)。

## 升级

以下只针对已确认的 **source project**。保留 PostgreSQL、Garage metadata/data 卷、旧 release、配置/secret/cert 和备份；升级不删除这些数据。迁移与应用切换有停机阶段，仓库没有维护模式、流量切换或自动 rollback 工具。

### 迁移前：识别、停写与备份

1. **Identify current release**：先按“命令环境与身份”确认 project/daemon，记录当前 api 的 image revision，并核对当前 checkout。backup 会再要求 api/web/object-storage label 一致且等于 EASYAUDIT_RELEASE；在对齐前停止，不先 pull/checkout 新代码。

   ```bash
   CURRENT_RELEASE="$(git rev-parse HEAD)"
   export EASYAUDIT_RELEASE="$CURRENT_RELEASE"
   cid="$($DC ps -q api)"
   image_id="$(docker inspect --format '{{.Image}}' "$cid")"
   docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id"
   git diff --quiet HEAD
   $DC run --rm --no-deps -T migrate alembic current
   $DC run --rm --no-deps -T migrate alembic heads
   ```

   记录 CURRENT_RELEASE、真实 running label、current revision、head、配置路径、project 和恢复备份位置。label/checkout 不符时找回运行 release 对应的干净检出，再开始备份，不通过重打标签跳过检查。

2. **Verify health / pause writes**：运行初始化章节的内部 live/ready，检查 HTTPS 登录和当前业务。维护者须暂停新业务写入并等待在途完成，暂停已安装的 reminder-sweep/cleanup-auth/cleanup-evidence-orphans/backup timers 及人工 writer；记录哪些原来启用、是否有仍运行的 oneshot。外部访问控制/停写程序 **Requires operator procedure**，仓库没有自动冻结所有写入的命令；无法确认停写完成就停止升级。此时保留 api/web/gateway 运行，因为 backup 的运行检查要求它们存在。

   ```bash
   # 仅针对已确认 source、且已安装的这些 unit；先记录原状态，未安装者不照抄执行。
   sudo systemctl stop easyaudit-reminder-sweep.timer easyaudit-cleanup-auth.timer \
     easyaudit-cleanup-evidence-orphans.timer easyaudit-backup.timer
   systemctl list-units --type=service --state=running
   ```

3. **Create / verify pre-upgrade backup while checkout matches running release**：在独立备份存储运行备份（会按既定保留策略删除该 backup root 的过期包，先确认目录身份）。只有 exit=0 且 bundle-only verify 成功的包作为正常升级恢复点；exit=3 先处理 degraded，不继续升级。记录工具输出的确切目录，不能凭完整目录名判断健康。

   ```bash
   export EASYAUDIT_BACKUP_DIR=/srv/easyaudit-backups
   deploy/backup/backup.sh
   PRE_UPGRADE_BACKUP='<本次 BACKUP OK 输出的完整目录>'
   deploy/backup/verify.sh "$PRE_UPGRADE_BACKUP" --bundle-only
   python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print({k:m[k] for k in ("release_sha","alembic_revision","backup_timestamp","integrity")})' "$PRE_UPGRADE_BACKUP/manifest.json"
   ```

   将 manifest release/revision 与上一步记录比对，受限保存旧配置/凭证。停写后取得的已验证恢复点仍须按实际 backup_timestamp 评估可能丢失的后续写入，不承诺零 RPO。

4. **停止应用，保留数据服务和卷**：人工确认 writer 均已停止，然后停止当前应用。不要解除停写直到新版本完成验收。

   ```bash
   $DC stop gateway api web
   ```

### 取得目标 release、审查迁移、切换

5. **Obtain approved target release**：只取得维护者批准的完整 SHA；本地配置是 ignored 文件，另行核对目标版本需要的配置，不打印 secrets。

   ```bash
   git fetch origin
   TARGET_RELEASE='<已批准的完整 release SHA>'
   git diff "$CURRENT_RELEASE" "$TARGET_RELEASE" -- alembic/versions deploy/compose.yaml Dockerfile
   git checkout --detach "$TARGET_RELEASE"
   export EASYAUDIT_RELEASE="$(git rev-parse HEAD)"
   ```

6. **Build target images**：`$DC --profile migrate build`。构建失败尚未执行 migration、未启动新应用；保留 source 数据服务，走下表失败决策。

7. **Inspect migration path**：`$DC run --rm --no-deps -T migrate alembic history --verbose` / `alembic heads` / `alembic current`。current 应等于记录的旧 revision；审查旧 revision 到目标 head 的每份 migration 源码、数据影响和应用兼容证据。`--no-deps` 防止这些检查/迁移命令顺便拉起或重建数据服务。PostgreSQL/Garage 镜像或数据布局变更需要单独经维护者验证的升级程序，不能由本流程自动认定兼容；没有证据则停止。`downgrade()` 存在不证明安全回退：例如 0008 会 drop evidences，0013 会 drop create-idempotency 表，0014 会 drop scheduler_runs；具体路径审查不由这些例子代替。

8. **Execute migration**：记录输出/退出码，仅在上一步通过后运行 `$DC run --rm --no-deps -T migrate`（默认 `alembic upgrade head`），随后分别运行 `alembic current` / `alembic heads` 并核对。不假设异常后的事务已把全部状态恢复；失败立即进入停点。

9. **Deploy target application**：revision 确认后运行 `$DC up -d --wait gateway`；核对 api/web/object-storage 实际运行 image label 都为 TARGET_RELEASE。API 启动不会自动迁移。

10. **Post-upgrade verification**：内部 live/ready、HTTPS 认证、两场景 catalog、已有 Plan/Case 读取及本次迁移相关业务检查；存储用授权 Evidence 上传/下载及 `$DC run --rm --no-deps -T api easyaudit-next verify-evidence` 验证。旧备份的完整 live verify 可能因升级后 revision/新增对象变化而失败，不用它当日常在线完整性探针。全部通过后由维护者恢复访问和原来启用的 timer，并核对下次触发/状态；保留旧恢复点直到本次变更验收结束。

### 失败决策与回退边界

| 停点 | 已发生的状态 | 操作者决策 / 验证 |
| --- | --- | --- |
| migration 尚未执行 | 新应用未激活；本流程没写数据库，数据服务/卷保留 | 修复构建/配置后继续，或切回 CURRENT_RELEASE、恢复旧配置并 re-export release，`$DC up -d --wait gateway`；内部健康和旧业务验收通过后恢复访问。若另有 writer/人工改动，先重新确认 DB 状态 |
| migration 失败 | 可能部分变更；新应用不应启动 | 保持应用/写入口停止；记录日志/退出码，用目标 migrate 镜像 `alembic current` 核对真实 revision 并检查受影响结构。仅 current 一行不证明所有数据回到原状。维护者决定 forward fix 或从已验证备份在独立目标恢复，不盲目启动旧/新应用 |
| migration 成功、新应用或验收失败 | 数据库已在新 schema，应用可能已启动/部分请求发生 | 暂停入口，`$DC stop gateway api web` 保留数据与日志。旧应用与新 schema 兼容、无损 downgrade、自动 application rollback 均 **NOT ESTABLISHED**；不能仅运行旧镜像或随便 downgrade。需维护者确认兼容的 forward fix，或使用旧恢复点到独立目标 |
| restore-based recovery | 从指定 backup_timestamp 的 release/revision 恢复，之后写入不自动合并 | 沿恢复章节到新的 isolated target，保留 source 供调查；按该备份的精确 release 启动和验证。重新开放/流量切换 Requires operator procedure，仓库未提供自动 cutover 或 source 新写入回灌 |

证据：[backup/release 检查](backup/backup.sh)、[恢复与 revision 顺序](backup/restore.sh)、[Alembic migrations](../alembic/versions/)、[迁移 engine](../alembic/env.py)。

## 认证维护

**SOURCE MAINTENANCE**：先确认 `$DC` 的 daemon/project 和 API 数据库属于待维护的 source；下述 cleanup 会删除该库的限流计数，`--clear-login-name` 会解除指定登录名的限流，不清空数据库或删除 Session。不要对未确认身份的数据库执行。

`$DC run --rm --no-deps -T api easyaudit-next cleanup-auth` 删除过期的 `login_throttle` 窗口（运维计数，不是业务数据），向 stdout 输出一行 JSON：删除条数和已过期 Session 的计数。**不删除也不修改任何 Session**：`auth_sessions` 是审计事件的 FK 锚点，试点期只增不删，过期靠 `expires_at` 保证不可用。某个登录名被限流误封（或被他人故意封锁）时，运维用 `$DC run --rm --no-deps -T api easyaudit-next cleanup-auth --clear-login-name <name>` 立即解封（名字会按登录规则规范化；输出里 `login_name_cleared` 是删除的窗口数）。`deploy/easyaudit-cleanup-auth.service/.timer` 是每天一次的 systemd 示例（安装方式同备份）。

## 每日自动提醒

调度在 Web 进程之外：systemd timer 每天 09:00（Asia/Shanghai）运行一次性容器 `easyaudit-next run-reminder-sweep`。`deploy/easyaudit-reminder-sweep.service/.timer` 是示例（改路径和账号后安装，要求同备份）：

```bash
sudo install -m 644 deploy/easyaudit-reminder-sweep.{service,timer} deploy/easyaudit-reminder-status.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now easyaudit-reminder-sweep.timer
systemctl list-timers easyaudit-reminder-sweep.timer     # 确认下次触发时间（Asia/Shanghai 09:00）
```

- 手动运行：`$DC run --rm --no-deps -T api easyaudit-next run-reminder-sweep [--as-of 2026-10-02T01:00:00Z] [--occurrence-key daily:2026-10-02]`。默认 `as_of` 是当前 UTC 时间，默认 key 是 `daily:<as_of 在 REMINDER_TIMEZONE（默认 Asia/Shanghai）下的日期>`，所以**同一天重跑是安全的**：已发出的提醒被数据库唯一约束去重，失败的候选会补上。stdout 是一行 JSON（`status`、`scanned_count`、`created_count`、`deduped_count`、`failed_count`、`error_summary`）；有候选失败或整体无法运行时退出码为 1，unit 会显示 failed。
- 查看状态：`$DC run --rm --no-deps -T api easyaudit-next scheduler-status [--job automatic_reminder_sweep] [--max-age-hours 26]` 输出最近一次运行和最近一次成功的 JSON。最近一次失败、最近一次成功早于 26 小时、或从未运行，退出码为 1。`easyaudit-reminder-status.service/.timer` 是每小时执行它的示例（先让 sweep 至少成功运行一次再启用，否则会报 `never_run`）；Pilot-7 上线检查清单的"提醒调度"就用它。
- 运行记录在表 `scheduler_runs`（运维记录，不影响业务，也不决定是否跳过运行）。进程崩溃会留下一条 `running` 记录，它不会阻止下一次运行；`scheduler-status` 不把它当作失败，只看最近一次成功。
- 排障：先看 `journalctl -u easyaudit-reminder-sweep` 里最近一次的 JSON，`error_summary` 只含异常类型和 SQLSTATE（如 `OperationalError/55P03` 是锁等待超时、`/40P01` 是死锁），不含 SQL 或数据；重跑即可补齐。

## Evidence 维护

两个命令都经 `$DC run --rm --no-deps -T api easyaudit-next ...` 运行（需要 postgres 和 object-storage 已启动），向 stdout 输出一行 JSON。

```bash
# SOURCE MAINTENANCE：先核对 $DC 的 daemon/project、数据库和 bucket 属于同一待维护 source。
# 删除操作会移除该 bucket 的超龄孤儿对象并中止超龄 multipart；先审查本次 dry-run，不删除卷。
# 孤儿清理：删除没有任何 Evidence 行引用、且早于 --min-age-hours（默认 24；删除时必须 ≥ 24，--dry-run 允许 ≥ 1）的对象，
# 并中止同样超龄的未完成 multipart。被引用的对象永远不删。第一次在新环境先 --dry-run。
$DC run --rm --no-deps -T api easyaudit-next cleanup-evidence-orphans --dry-run
$DC run --rm --no-deps -T api easyaudit-next cleanup-evidence-orphans

# 完整性校验：读回每个对象，核对存在、大小、sha256。有任何不一致退出码为 1。
$DC run --rm --no-deps -T api easyaudit-next verify-evidence [--organization-id UUID] [--limit N]
```

- `cleanup-evidence-orphans` 输出 `scanned`、`orphans`（含还太年轻的）、`deleted`、`kept_young`、`multipart_stale`、`multipart_aborted`、`skipped_referenced`、`failed`、`max_delete`、`deleted_but_registered`、`refused`；`failed`、`refused`、`deleted_but_registered` 任一非零时退出码为 1。`deploy/easyaudit-cleanup-evidence-orphans.service/.timer` 是每天一次的 systemd 示例（安装方式同备份）。从备份恢复后，bucket 比数据库引用的多出一些对象（见"备份"的一致性说明），它们在 min-age 之后被这个命令清理。
- **三条整体拒绝保护**（非 dry-run；任何一条触发保证**零删除、零中止**，退出码 1，JSON `refused` 写明原因，但执行时机不同）：
  - **revision 前置检查（在列举之前执行）**：
    - `revision_mismatch`：数据库的 alembic revision 不等于当前代码的 head（读出 `alembic_version` 的全部行，要求集合严格等于 `{head}`）。**在列举对象和未完成 multipart 之前执行**；不匹配立即拒绝返回。**注意**：前置检查拒绝时，输出中的 `scanned=0`、`orphans=0`、`multipart_stale=0` 等各项计数均为初始值 0，**不能用来判断桶里有什么**。
      处置：先核对数据库 revision、运行中镜像的 release、CLI 的 release 是否一致：
      ```bash
      cid="$($DC ps -q api)"
      image_id="$(docker inspect --format '{{.Image}}' "$cid")"
      docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image_id"
      git rev-parse HEAD
      $DC run --rm --no-deps -T migrate alembic current
      $DC run --rm --no-deps -T migrate alembic heads
      ```
      若版本不对齐，换回与数据库一致的镜像与检出；若确实需要迁移升级，**转到本页的[完整升级流程](#升级)**（停写、停 timer、备份并验证、`--no-deps migrate`、复验），绝不能直接运行迁移绕过安全流程。
  - **完整列举后的两项保护（在完整列举之后、第一次删除/中止之前检查）**：
    通过前置检查后，命令在第一次写操作之前完整列举对象和未完成 multipart，算出完整候选集，随后进行两项检查：
    1. `no_evidence_rows`：数据库 `evidences` 是 0 行而桶里有 evidence 对象（`scanned > 0`）——几乎肯定连错了库，或恢复没有完成。先确认 `DATABASE_URL` 指向正确的库、恢复已完成，再重跑。
    2. `too_many_deletions`：要删的对象数超过 `--max-delete`（默认 100）。正常孤儿很少，一次很多说明出问题；先用 `--dry-run` 看清是什么，确认确实该删之后用 `--max-delete N` 调大上限重跑。
- **保护是启发式的，不绑定部署身份**：部署需确保 CLI 使用的数据库与对象存储配置属于同一环境；错桶 + 同 revision + 候选数不超限时，这三项保护拦不住。对象和未完成 multipart 都在第一次写操作之前列举完整，任一列举失败或保护拒绝均保证零删除、零中止。
- **已知窗口**：一条登记若在逐 key 复查之后、删除之前提交（需要登记被延迟超过 24 小时，只有 DB 黑洞类故障才可能），对象会被删而元数据保留。每次删除后命令会再查一次：命中则当场写 ERROR 日志 `evidence_object_deleted_while_registered`（`storage_key`、`evidence_id`），JSON 里 `deleted_but_registered > 0`，退出码非零（timer 显示 failed）；`DeleteObject` 报错时同样复查。命令中途异常失败时 JSON 仍输出已累计的计数，并带 `error`（异常类型）。处理：从最近一份备份把该 key 的对象拷回 bucket，再用 `verify-evidence` 确认。
- **时钟与耗时**：min-age 依赖 Garage 与运行命令的主机时钟一致，部署时保持时钟同步；multipart 的年龄不代表它不活跃，所以单次上传的耗时必须远小于 min-age。
- **`verify-evidence` 与 `deploy/backup/verify.sh` 的区别**：`verify.sh BACKUP_DIR` 以**某一份备份包的 manifest** 为基准——先校验备份包本身，再（不加 `--bundle-only`）把线上 bucket 与 DB 对照这份 manifest，用于"这个环境是否还原成了这份备份"；`verify-evidence` 不需要备份包，枚举数据库 Evidence 引用并读回对应对象，核对存在、大小、sha256，走应用自己的 S3 客户端、可按组织/数量限制，用于恢复后的验证和平时的故障诊断。它不要求整个 bucket 与旧 manifest 的 key 集合相同，也不是只发 HEAD 的轻量探针；Evidence 丢失还会在下载时以 500 + `evidence_object_missing` 日志暴露。
- 下载（`GET /api/v1/evidences/{id}/content`）不重算 sha256；它只在发送响应头之前比较存储报告的大小与元数据（不一致 → 500 + ERROR `evidence_object_size_mismatch`，不发送内容）。内容层面的完整性由 `verify-evidence`（线上）和备份时的核对（备份）保证。

## 备份

设计目标为 RPO ≤ 24h、RTO ≤ 4h，**不是目标机器已达标的声明**。工具在 `deploy/backup/`，通过一次性 `db-tool` / `object-tool` 容器访问数据库和对象存储（仅 backend、无发布端口、非 root、cap_drop: ALL）。需要 docker compose、python3、flock、GNU stat，以及拥有 secret 目录和备份目录的非 root Docker 运维账号；容器以调用者 uid 写备份目录。

在已经确认的 source project、运行 release 对齐的干净检出执行。确认 `/srv/easyaudit-backups` 是该 source 的备份存储，且与数据卷不同盘；命令完成发布后会清理该目录中到期的备份，最新 integrity-ok 包保留。source 的 DB/Garage 卷不会作为备份目录清理。

```bash
export EASYAUDIT_RELEASE="$(git rev-parse HEAD)"
EASYAUDIT_BACKUP_DIR=/srv/easyaudit-backups deploy/backup/backup.sh
```

- 备份目录**权限必须是 0700 且归调用者所有**，不满足即拒绝。每次生成 `easyaudit-backup-<UTC 时间戳>/`，包含 `database.dump`（pg_dump -Fc）、`objects/`（rclone S3 镜像，不依赖 Garage 内部卷）和 `manifest.json`。先写 `.partial`，manifest 构建返回 0 **或 3** 都会 rename 成完整目录；完整目录表示产物已发布，不等于健康成功。
- **时间与一致性**：先 DB dump，再 object mirror。DB 是 PostgreSQL 一致快照；已登记 Evidence 对象按服务端 key 只写一次、不覆盖，因此无丢失/完整拷贝时后续镜像可能包含 dump 之后新增的对象，成为 dump 引用集合的超集。多余对象是相对于 dump 的孤儿，不是跨存储原子快照保证。对象缺失或外部篡改时超集前提不成立；构建 manifest 会核对 dump 的引用与镜像的 key/size/sha256，将缺失/不一致列入 integrity_problems。不要仅因同步先后便宣称所有历史引用都完整。
- **manifest**：`backup_timestamp`（UTC，dump 开始时刻）、`release_sha`（读运行中 api 镜像的 revision label，不信任环境变量；api/web/object-storage 三个镜像的 label 必须一致且等于 `EASYAUDIT_RELEASE`；脚本不读取 HEAD，检出是否对齐由操作者核对）、`alembic_revision`（取自 dump 内的 `alembic_version`）、dump 的 sha256、每个对象的 key/size/sha256、各服务的镜像 tag、开始时间与耗时。
- **保留策略**：默认保留 14 天，`EASYAUDIT_BACKUP_RETENTION_DAYS` 可改。新包发布之后才清理过期备份，发布的包可能为 ok 或 degraded。degraded 备份照常按天数过期，但**最近一份 `integrity: ok` 的备份永远不删**（否则对象持续缺失时，14 天后会把最后一份健康备份清掉）；过期的陈旧 `.partial` 会清理，名字不符合 `easyaudit-backup-<时间戳>` 格式的目录不会被碰。
- **退出码和产物**：见下表；timer 对非零显示 failed。预升级恢复点要求 exit 0、integrity=ok 且 bundle-only verify 通过；degraded 只能作为有已知缺失/不一致的恢复资料，不算健康恢复资格。
- **调度与 RPO**：`easyaudit-backup.service` / `easyaudit-backup.timer` 是 systemd 示例，**每 12 小时一次**（02:30、14:30，无随机延迟），为一次失败后的下一次调度预留间隔。实际成功时间还取决于执行延迟、耗时和故障；仅靠调度并不能保证 RPO。用 `deploy/backup/check-freshness.sh`（`EASYAUDIT_BACKUP_DIR`、`EASYAUDIT_BACKUP_MAX_AGE_HOURS`，默认 24）做监控，最近一份 `integrity: ok` 备份的 `backup_timestamp` 早于 24h 就以非零退出（degraded 和 `.partial` 不算）。`easyaudit-backup-freshness.service/.timer` 是每小时执行它的示例；Pilot-7 上线检查清单的"备份新鲜度"就用它。安装：改路径和账号后 `systemctl enable --now easyaudit-backup.timer easyaudit-backup-freshness.timer`。
- **不进备份包**：secret 文件和 TLS 证书；source 原文件仍需单独受限保管。独立空目标可以初始化自己的新 PG/Garage/S3 凭证和证书，用户密码哈希及 Session 行来自数据库备份。它不是修改既有 source 凭证的轮换流程；证书域名与客户端信任仍须重新核对。

| backup.sh exit | Manifest / 产物 | 操作含义 |
| --- | --- | --- |
| 0 | integrity=ok，完整目录已发布 | 备份生成流程成功；继续用 verify.sh --bundle-only 核对保管副本，不等于异地/加密/目标机恢复资格已经取得 |
| 3 | integrity=degraded，完整目录仍发布并保留 | 数据库快照保留，但引用对象有完整性问题；看 manifest 清单，修复来源或由维护者决定受损数据恢复，不能当成正常健康成功 |
| 1 | 流程失败 | 看失败阶段/日志；发布前的失败会清理当前 .partial，发布后的目录存在也不能替代 exit 与 manifest 检查。不凭目录名认定有可用恢复点 |

restore 的 `check_bundle` 先用不带 --fail-degraded 的 verify-bundle 核对包文件与 manifest。`environment` 随后再带 --fail-degraded 校验：degraded 包在 build、启动和任何写入之前被拒绝（退出 1，无 opt-in 开关），因为最终 `verify.sh` 始终带 --fail-degraded，degraded 包注定通不过。`database` / `objects` 分步模式不开放流量，仍允许 degraded 包并在首次写入前向 stderr 打印问题清单，仅用于调查。

### 安装和验证备份调度

仅针对已确认的 **source project**：先在独立备份存储准备调用者可写、归调用者所有且为 0700 的 backup root。若 `/srv` 不可写，由主机管理员建立并交给该非 root 运维账号，不改用 root 跑 backup。

从 `deploy/backup/easyaudit-backup.{service,timer}` 和 `easyaudit-backup-freshness.{service,timer}` 准备主机配置副本，放在下例 `/srv/easyaudit-config/systemd/`。安装前审核副本中的 User、WorkingDirectory、ExecStart 路径、backup root，以及 backup service 的 COMPOSE_PROJECT_NAME、EASYAUDIT_SECRETS_DIR/EASYAUDIT_CERTS_DIR Environment，确保与手动命令相同；Shell 的 export 不会自动进入 systemd。示例 unit 的 `/opt/easyaudit` 和 User=easyaudit 不是现场事实。保留原有 unit 副本和启用状态，以便配置失败时恢复。

```bash
# SOURCE MAINTENANCE：这些是已经审核的主机副本；backup 会按保留策略删除所确认 root 的过期包。
sudo install -m 644 /srv/easyaudit-config/systemd/easyaudit-backup.{service,timer} \
  /srv/easyaudit-config/systemd/easyaudit-backup-freshness.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start easyaudit-backup.service
systemctl show easyaudit-backup.service -p Result -p ExecMainStatus -p ActiveState
journalctl -u easyaudit-backup.service -n 50 --no-pager
sudo systemctl start easyaudit-backup-freshness.service
sudo systemctl enable --now easyaudit-backup.timer easyaudit-backup-freshness.timer
systemctl list-timers easyaudit-backup.timer easyaudit-backup-freshness.timer
```

先确认手动 service exit=0、日志给出健康包且 freshness 通过，再启用 timer；exit=3 是 retained degraded，不能跳过处理。oneshot 完成后可显示 inactive，核对 exit/result 与日志。安装其他维护 timer 使用同一身份审核；删除型任务先完成本页对应 dry-run。failed unit/探针非零只提供信号，外部告警接收、通知与值守响应 **Requires operator procedure**，仓库未自动接入。

### 已知限制

- **和数据在同一块盘上的备份不算备份。** 备份目录必须在另一块盘或另一台机器上；异地拷贝由运维负责，本仓库不做异地同步。
- 备份包未加密，只靠目录 0700 保护，包含全部业务数据和证据文件。加密与异地同步不在 Pilot-1B 范围内。
- 备份在线进行，不停服务：DB 是 `pg_dump` 的一致快照，对象是 dump 之后的镜像（见上文）。
- CI 恢复演练使用脚本的小数据集，输出只代表该次测量。目标机 RTO 还取决于实际数据量、镜像构建/拉取和磁盘速度；开放试点前需在目标机器上按实际数据量演练，不能用 CI 记录代替。

## 恢复

### Source 与 isolated restore target

**Source deployment** 是正在运行或需保留数据的环境：source project、PostgreSQL volume、Garage metadata/data、secret/config/cert 都须保留。恢复不要求销毁 source，不删除 source 卷，也不把它清空后当恢复目标。

**Restore target** 必须 separate / isolated / disposable / operator-confirmed。本流程采用操作者另外准备的 Docker 主机/VM/daemon和独立 release checkout；仓库没有自动 provision isolated target 的工具。仅改 COMPOSE_PROJECT_NAME 不足以证明隔离：base Compose 固定 edge 网段 172.30.10.0/24、gateway IP 与端口，同一 daemon 上的 source/target 可能冲突；同主机并行部署需要另行核实配置和全部消费者，不在本例中宣称支持。

恢复前人工记录/核对以下对应关系，任一不明就停：

| 身份 | 必须确认的内容 |
| --- | --- |
| Source | 原 Docker 主机/daemon/context、source project；其 PostgreSQL/Garage 卷和配置需保留 |
| Target | 独立主机/daemon/context、独立 project、secret/cert 绝对路径、证书域名、网络与发布端口；不指向 source |
| Database | target 内 postgres:5432、database/user easyaudit；实际 PostgreSQL volume Mounts 与 project 标签 |
| Object storage | target Garage 的 object_meta/object_data；内部 endpoint http://object-storage:3900、bucket easyaudit-evidence、region garage；凭证属于该 target |
| Release / backup | 选定完整备份目录/manifest、release_sha、alembic_revision、backup_timestamp、integrity；目标 HEAD 和 EASYAUDIT_RELEASE 必须等于 manifest release |

**empty-target guard 只能防止 restore 写入已经非空的目标，不能代替操作者确认目标身份。** 非系统 schema 有表或 bucket 列举非空就拒绝，没有 --force；拒绝时保持 source 和失败 target 的证据，选择另一个确认过的独立空目标，不用删除当前 project 数据来消除错误。历史版本脚本或文档中的清空、删除建议不适用于 source；恢复始终使用独立的空目标。

### 在独立目标执行

先将指定备份复制到 target 的受限目录，保留 source 原件，重新校验复制后的包。下列所有命令**只在独立可丢弃 target 主机/checkout**执行，不在 source 的 Shell 执行：

```bash
DC="docker compose -f deploy/compose.yaml"
export COMPOSE_PROJECT_NAME='easyaudit-restore-<incident-id>'
export EASYAUDIT_SECRETS_DIR='/srv/easyaudit-restore/<incident-id>/secrets'
export EASYAUDIT_CERTS_DIR='/srv/easyaudit-restore/<incident-id>/certs'
BACKUP_DIR='<已确认的完整备份目录绝对路径>'
docker context show
git status --short
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print({k:m[k] for k in ("release_sha","alembic_revision","backup_timestamp","integrity")})' "$BACKUP_DIR/manifest.json"
deploy/backup/verify.sh "$BACKUP_DIR" --bundle-only
```

替换所有尖括号输入为人工确认的真实身份，不保留示例字符串。如果包为 degraded，此次 bundle-only verify 会失败：不要误认为完全不能读取包，也不要把失败当健康成功；degraded 包会被 `restore.sh environment` 直接拒绝；受损数据的调查须维护者明确接受问题清单，改用 `restore.sh database` / `objects` 分步写入独立目标，不能得到 `RESTORE OK`，也不开放服务。

在**目标专用干净检出**（不是修改 source checkout）取 manifest 指定的版本，export release；按第 1 节在 target 的新目录准备新 secrets 和有效 TLS 证书。禁止先 migrate/bootstrap：恢复数据库需要空库。

```bash
BACKUP_RELEASE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_sha"])' "$BACKUP_DIR/manifest.json")"
git checkout --detach "$BACKUP_RELEASE"
export EASYAUDIT_RELEASE="$BACKUP_RELEASE"
git status --short
$DC --profile migrate build
$DC up -d --wait postgres object-storage
$DC ps -a
for svc in postgres object-storage; do
  cid="$($DC ps -q "$svc")"
  docker inspect --format '{{.Name}} {{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} -> {{.Destination}}; {{end}}{{end}}' "$cid"
done
$DC run --rm -T db-tool psql -X -At -v ON_ERROR_STOP=1 -c "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')"
$DC run --rm -T object-tool lsf --max-depth 1 ea:easyaudit-evidence
```

确认实际 Mounts 为 target project 的 postgres_data/object_meta/object_data、SQL 输出 0、对象列举为空，并人工确认这些确实是 target；不要把“输出为空”当部署身份认证。environment 会重复 build/up 和两个 empty checks，提供写入前保护，已有 source 不参与。

```bash
deploy/backup/restore.sh environment "$BACKUP_DIR"
# 成功时 verify.sh 与 verify-evidence 已在脚本内通过，gateway 最后才启动；
# 失败时 gateway/web/api 已被自动停止，退出码非零。
```

### 分阶段写入、启动与失败含义

下表“尚未启动”指本次 restore 还没有执行应用启动阶段；若目标原有应用进程，脚本不会在前置失败时自动停止它。正常流程要求目标为另外准备的独立空环境。

| 阶段 | environment 实际行为 | 此时已经写入 / 尚未发生 / 失败含义 |
| --- | --- | --- |
| precheck | 目录/manifest 存在、依赖命令、非 root；release=HEAD/env，Compose ps 返回已有 api 时核对 label；tracked checkout clean、secret/cert 文件存在；文件 hash 与 manifest 校验 | restore 尚未写 DB/对象、尚未启动应用；degraded 警告在包校验之后、首次写入之前打印。untracked build 输入仍由操作者检查 |
| build / data services | 构建镜像，启动 postgres/object-storage | 可能已创建 target 容器/空卷与 Garage bootstrap 配置，尚未写备份 DB/对象，应用未启动；失败保留目标记录 |
| target-empty validation | 同时 require_empty_database / require_empty_bucket | 任一非空即拒绝，两者备份数据都未写，应用未启动；不自动清空、不切换目标、不覆盖 |
| database write | 重做 DB 空检查；pg_restore --single-transaction --exit-on-error；之后比较 DB revision 与 manifest | pg_restore 成功后 DB 已写，对象尚未拷；revision 不符会失败但不删除已恢复 DB。pg_restore 失败查日志/实际状态，不把所有阶段当一个事务 |
| object write | 重做 bucket 空检查，然后 copy objects | DB 已写；copy 失败可能留部分 target 对象，应用未启动；不做自动跨存储回滚，再试可能被 empty guard 拒绝 |
| revision validation | 写入后比较 alembic current = manifest revision = release head | DB/对象已写，应用尚未启动；不符退出，不自动 downgrade/清理卷 |
| data verification | verify.sh（只需 postgres/object-storage）：--fail-degraded 检查包，再核对 live revision、bucket 全 key/size/sha256 和 DB Evidence 引用 | DB/对象已写，**没有任何入口在运行**；失败退出 1，不开放服务，不撤销写入、不删卷 |
| internal application start | up -d --wait api web（仅内部网络，不发布端口），再 run api `easyaudit-next verify-evidence` | 失败时 EXIT trap 执行 `stop gateway web api`（不是 down -v），打印这三个服务的日志尾部，数据卷、日志、manifest 全部保留，退出非零 |
| gateway | up -d --wait gateway | 唯一发布 443 的入口，仅在上述全部通过后启动；启动失败同样自动 stop 并非零退出 |
| final result | 只有以上全部成功才打印 RESTORE OK，退出 0 | 非零退出查看停点；入口服务已停止，需要人工排查后再决定是否重新开放，不能因容器 healthy 就开放服务 |

分步模式：`deploy/backup/restore.sh database "$BACKUP_DIR"` 只要求 postgres running、DB 空，校验包并写 DB，随后核对 manifest revision；不写对象、不启动应用、不检查 release head 相等。`restore.sh objects` 只要求 object-storage running、bucket 空，校验包并写对象，不写 DB/检查其 revision/启动应用。两者仍先核对 release，均允许包文件一致的 degraded 资料并提前警告（`environment` 则拒绝 degraded 包）；命令退出 0 只表示该子步骤完成，不能替代整环境最终 verify 和业务验收。

`verify.sh BACKUP_DIR --bundle-only` 不访问部署，只查包（含 degraded 问题）；无该参数还需要 EASYAUDIT_RELEASE、postgres/object-storage，核对 live revision 与 manifest，完整列举/读回对象和 Evidence 引用。有多余 live key 也会失败，所以部署重新开放写入或清理了备份带来的孤儿之后，不再要求 live bucket 永远等于旧 manifest；日常 DB↔对象校验使用 verify-evidence。

恢复失败时保留 source、备份原件、target 和日志/manifest/真实 revision；若已启动应用，在**确认的 target** 执行 `$DC stop gateway api web` 关闭入口并保留数据。恢复工具未提供失败后自动清理、覆盖重试或继续点；维护者调查停点，选择另外确认的空目标重新恢复。成功也需内部健康、原账号 HTTPS 登录、已有 Case/Evidence 读回、真实 Evidence 字节验证；Session 数据来自备份，重新开放前按维护者程序评估旧 Session 和流量切换，不宣称已完成全局撤销/自动 cutover。

证据：[restore.sh](backup/restore.sh)、[verify.sh](backup/verify.sh)、[lib.sh](backup/lib.sh)、[manifest.py](backup/manifest.py)、[backup manifest tests](../tests/unit/test_backup_manifest.py)、[guard/顺序 tests](../tests/unit/test_deploy_compose.py)。

### 恢复演练

**DISPOSABLE TEST/DRILL TARGET ONLY**：drill.sh 固定 project=`easyaudit-drill`，内部执行 `down -v` 删除该 project 的数据卷，并删除临时 secrets/certs；只允许在专用可丢弃 Docker 主机/daemon运行。先确认该固定 project 未承载需保留数据，source 不在该 project。它不是正常 restore prerequisite，也不是 source 清理程序；不要同时运行同名演练。

`deploy/backup/drill.sh` 的 **DISPOSABLE TEST/DRILL TARGET ONLY** 流程：临时证书/secrets → migrate/bootstrap/process_review publication → 真实网关 API 创建 Plan/Case/Finding/Action 并上传三个文件（含 9 MiB multipart）→ bucket hash 比对 → backup → 内部 `down -v`（仅删除已确认的 easyaudit-drill 卷，不得用于 source）→ 新凭证/证书 → environment restore → revision/原账号/Case/Finding/Evidence 元数据与字节核验。随后测试非空目标和三个入口 release mismatch；故意删除演练对象后断言 backup exit=3、degraded 保留、verify 失败、freshness 仍选择先前 ok 包；最后演练非空 bucket 在 DB 写入前拒绝。RTO 超过 DRILL_RTO_LIMIT_SECONDS（默认 14400）或记录不可写均失败。输出 restore-drill-record.json（restore_started_at、restore_completed_at、actual_rto_seconds、backup_timestamp、release_sha、result）。CI 的 backup-restore-drill job 上传/打印记录，不是仓库约定的 required check；不能把 CI 小数据集的测量预填成目标机达标。

恢复后 `drill_api.py check` 通过 API **下载每个 Evidence**（含 9 MiB 的多段上传文件），把字节的 sha256 与元数据以及上传前本地文件的 sha256 比对，并检查 `Content-Disposition`（`filename*` 解码后等于原文件名）和 `nosniff`；随后 `verify-evidence` 必须零不一致、`cleanup-evidence-orphans --dry-run` 必须找不到孤儿（顺便在真实的 Garage 上走一遍列举接口）。第 8 步故意删掉一个对象后，`drill_api.py lost` 断言它的下载是带 request_id 的 500（不是 404），`verify-evidence` 必须失败并点名该 Evidence。

## 冒烟测试

**DISPOSABLE TEST/DRILL TARGET ONLY**：`deploy/smoke.sh` 固定 project=`easyaudit-smoke`，用临时证书/secrets 运行 build → label → migrate → up → HTTPS/内部 ready → 未认证上传 401、网关超限 413 → 端口检查，最后内部 `down -v` 删除该测试 project 卷。不得用于 source deployment；运行前确认该固定 project 可丢弃，使用专用 Docker 主机/daemon，不并行同名测试。需要 docker compose、git、openssl、curl、python3，端口冲突可设置 EASYAUDIT_HTTPS_PORT。CI 对应 deploy-smoke；它证明拓扑冒烟，不证明两个场景完整业务 Ready。

## 说明

- 对象存储为 Garage（单节点）。API 用 `s3_access_key_id`/`s3_secret_access_key` 访问 bucket `easyaudit-evidence`（内部端点 `http://object-storage:3900`，region `garage`），凭证以 secrets 文件挂载，环境变量只给文件路径（`OBJECT_STORAGE_*_FILE`）。API 的 `/health/ready` 含 `object_storage`，只检查 endpoint 可达（不签名的 HEAD，任何 HTTP 状态都算通），**不校验凭证和 bucket**；凭证或 bucket 不对会在第一次上传时以 503 暴露。
- Evidence 上传限制由 `EVIDENCE_MAX_BYTES`（默认 25 MiB）和 `EVIDENCE_ALLOWED_CONTENT_TYPES` 控制。网关的 `request_body max_size`（`Caddyfile`，26 MiB）要略大于应用上限：调大应用上限时同步改它。
- 上传失败后可能留下孤儿对象（登记失败且删除也失败）或未完成的 multipart（进程崩溃）；它们不在任何 Evidence 行里引用，备份会把前者当作多出来的对象带走，由 `cleanup-evidence-orphans` 清理（见"Evidence 维护"）。
- API 只信任来自网关固定地址（`172.30.10.10`）的代理头。若该网段与内网冲突，同时修改 `compose.yaml` 中 `edge` 网段、网关 `ipv4_address` 和 `FORWARDED_ALLOW_IPS`（测试会检查后两项一致）。
