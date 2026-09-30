# 生产部署（私有网络）

```text
Private Network → gateway (Caddy, 仅 :443) → { web (nginx, SPA), api (FastAPI) }
                                               api → { postgres, object-storage (Garage, S3) }
```

- 只有 `gateway` 发布端口，且只有 443（无 80，不做 HTTP 跳转）。
- 除 gateway 外没有任何宿主机端口发布；`backend` 网络是 `internal: true`，禁止容器外联。注意 `internal` 并不阻止 Linux 宿主机直接访问容器 IP，宿主机本身应视为可信，并靠宿主机防火墙限制访问。
- 所有容器以非 root 运行，所有镜像固定到具体版本（`tests/unit/test_deploy_compose.py` 强制）。
- 开发用的根目录 `compose.yaml` 与本目录无关，不要混用。

以下命令都在仓库根目录执行，`DC="docker compose -f deploy/compose.yaml"`。

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

`git pull` → `$DC build` → `$DC run --rm migrate` → `$DC up -d`。迁移始终在新 API 启动前手动执行。

## 冒烟测试

`deploy/smoke.sh` 用临时证书和 secrets 完整跑一遍（build → migrate → up → HTTPS 验证 → 无非网关端口发布 → down -v）。前置条件：docker compose、openssl、curl、python3。本机 443 被占用时设置 `EASYAUDIT_HTTPS_PORT`。CI 中对应 `deploy-smoke` job。

## 说明

- 对象存储为 Garage（单节点）。应用目前不使用它；证据文件功能（Pilot-4A）接入时使用 `s3_access_key_id`/`s3_secret_access_key` 和 bucket `easyaudit-evidence`，内部端点 `http://object-storage:3900`，region `garage`。
- API 只信任来自网关固定地址（`172.30.10.10`）的代理头。若该网段与内网冲突，同时修改 `compose.yaml` 中 `edge` 网段、网关 `ipv4_address` 和 `FORWARDED_ALLOW_IPS`（测试会检查后两项一致）。
- 备份与恢复见 Pilot-1B，本目录尚未覆盖。
