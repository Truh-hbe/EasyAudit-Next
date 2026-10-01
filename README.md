# EasyAudit-Next

EasyAudit-Next 是面向跨部门协作的通用审查平台。它以 Review Core 为中心，通过版本化 Scenario 承载不同审查场景。目前支持过程审查 `process_review@1` 和合规审查 `compliance_review@1`。旧版 `EasyAudit_Project` 独立维护，本仓库不承担与其兼容的义务。

## 当前能力

- 组织、部门、用户，本地账号与服务端 Session，最小化管理后台，凭证重置。
- 审查计划 → 审查案例 → 发现 → 整改项与证据元数据 → 整改提交 → 验证 → 关闭。
- 个人工作台、站内通知、管理进度与逾期视图、手动催办、自动提醒（调度器尚未接入）。
- React 产品界面，覆盖以上全部流程。

尚未具备：生产部署、证据文件存储、定时调度、导出。见 [路线](docs/roadmap.md)。

## 快速开始

要求 Python 3.12+、Node 22、Docker Compose。

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db
alembic upgrade head
uvicorn easyaudit_next.main:app --reload
```

首次迁移后创建首个组织与系统管理员（密码只通过终端隐藏输入读取），并为组织发布场景：

```bash
easyaudit-next bootstrap-admin \
  --organization-name "Example Manufacturing" \
  --admin-name "Platform Administrator" \
  --login-name admin
easyaudit-next publish-scenario --organization-id <org-id> --key process_review --version 1
```

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
  export PGPASSWORD=easyaudit DATABASE_URL=postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit_test
  dropdb -h localhost -U easyaudit --if-exists easyaudit_test && createdb -h localhost -U easyaudit easyaudit_test
  alembic upgrade head && EASYAUDIT_RUN_POSTGRES_TESTS=1 pytest
)
```

## 文档

- [docs/architecture.md](docs/architecture.md)：架构规则
- [docs/domain.md](docs/domain.md)：领域模型与场景
- [docs/roadmap.md](docs/roadmap.md)：路线
- [docs/adr/](docs/adr/)：架构决策记录
- [AGENTS.md](AGENTS.md)：开发流程与 Agent 分工

## License

尚未选择开源许可证。在许可证明确前，本仓库代码不授予复制、修改或分发许可。
