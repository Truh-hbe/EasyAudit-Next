# EasyAudit-Next

EasyAudit-Next 是面向跨部门协作的通用审查平台。它以 Review Core 为中心，通过版本化 Scenario 承载不同审查场景。目前支持过程审查 `process_review@1` 和合规审查 `compliance_review@1`。旧版 `EasyAudit_Project` 独立维护，本仓库不承担与其兼容的义务。

## 当前能力

- 组织、部门、用户，本地账号与服务端 Session，最小化管理后台，凭证重置。
- 审查计划 → 审查案例 → 发现 → 整改项与证据文件 → 整改提交 → 验证 → 关闭。
- 个人工作台、站内通知、管理进度与逾期视图、管理快照导出（CSV/XLSX）、手动催办、每日自动提醒。
- React + Ant Design 产品界面，覆盖以上全部流程。
- 私有网络部署（HTTPS 网关、对象存储、备份与恢复演练）、健康检查、结构化日志，见 [deploy/README.md](deploy/README.md)。

尚未具备：OIDC/SSO、MFA、邮件或企业 IM 通知、数据保留策略。见 [路线](docs/roadmap.md)。

本仓库指引面向开发与经维护者批准的受控私网试点，不代表 GA 或通用生产支持。部署拓扑、工具和 CI 演练存在，不等于目标机器已经通过运行资格验证；支持边界见 [SECURITY.md](SECURITY.md)。

## 快速开始

要求 Python 3.12+、Node 22、Docker Compose。

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db
alembic upgrade head
uvicorn easyaudit_next.main:app --reload
```

首次迁移后创建首个组织与系统管理员（交互式输入密码，不把密码放在命令行）。然后经 HTTPS 前端登录，用 `GET /api/v1/me` 响应的 `organization_id` 替换下面的 `<org-id>`，为该组织发布两个精确 v1 场景：

```bash
easyaudit-next bootstrap-admin \
  --organization-name "Example Manufacturing" \
  --admin-name "Platform Administrator" \
  --login-name admin
easyaudit-next publish-scenario --organization-id <org-id> --key process_review --version 1
easyaudit-next publish-scenario --organization-id <org-id> --key compliance_review --version 1
```

重复发布同一版本会被拒绝，不是幂等成功。CLI 注册了场景代码不等于组织已经发布它。完整的组织识别、部门/用户、首次改密、catalog 与 Plan → Case 验收见 [首次部署到业务 Ready](deploy/README.md#首次部署到业务-ready)。本地开发的对象存储配置入口见 [配置参考](docs/operations/configuration.md)：默认不配置对象存储时，上传为 503、readiness 失败；本地前端也需要受信任的 HTTPS，才能使用 Secure Session Cookie。

前端：

```bash
cd web && npm ci && npm run dev
```

## 验证

```bash
ruff check . && mypy
python scripts/check_architecture.py
python scripts/check_openapi.py
EASYAUDIT_RUN_POSTGRES_TESTS=1 pytest
cd web && npm run typecheck && npm run lint && npm run test && npm run test:browser
```

全量 PostgreSQL 测试必须用全新的库：部分多 Session / 并发测试会真实提交数据，bootstrap 测试要求库里没有 Organization，CI 也是每次空库。共享开发库 `easyaudit` 仍用于日常开发和单个测试。

```bash
(
  # DISPOSABLE TEST TARGET ONLY：先确认 localhost:5432/easyaudit_test 是可丢弃测试库。
  # 下方 dropdb 删除该测试库全部数据；不得替换成 source deployment 或需保留的库。
  export PGPASSWORD=easyaudit DATABASE_URL=postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit_test
  dropdb -h localhost -U easyaudit --if-exists easyaudit_test \
    && createdb -h localhost -U easyaudit easyaudit_test \
    && alembic upgrade head \
    && EASYAUDIT_RUN_POSTGRES_TESTS=1 pytest
)
```

## 文档

- [docs/architecture.md](docs/architecture.md)：架构规则
- [docs/domain.md](docs/domain.md)：领域模型与场景
- [docs/design.md](docs/design.md)：前端 UI 规范
- [docs/roadmap.md](docs/roadmap.md)：路线
- [docs/adr/](docs/adr/)：架构决策记录
- [deploy/README.md](deploy/README.md)：私网部署、升级/失败决策、备份、隔离恢复与初始化的主要操作入口
- [docs/operations/configuration.md](docs/operations/configuration.md)：配置来源、生效与密钥维护边界
- [SECURITY.md](SECURITY.md)：支持范围与安全报告
- [AGENTS.md](AGENTS.md)：开发流程与 Agent 分工

## License

尚未选择开源许可证。在许可证明确前，本仓库代码不授予复制、修改或分发许可。
