# EasyAudit-Next

EasyAudit-Next 是面向跨部门协作的通用审查平台。它以 Review Core 为中心，通过版本化 Scenario 承载不同审查场景。目前支持过程审查 `process_review@1` 和合规审查 `compliance_review@1`。旧版 `EasyAudit_Project` 独立维护，本仓库不承担与其兼容的义务。

## 当前能力

- 组织、部门、用户，本地账号与服务端 Session，最小化管理后台，凭证重置。
- 审查计划 → 审查活动 → 审查发现 → 整改项与证据文件 → 整改提交 → 验证 → 关闭；计划与活动创建支持幂等重试。
- 个人工作台、站内通知、管理进度与逾期视图、手动催办；每日自动提醒的外部调度与运行记录；管理快照 CSV/XLSX 导出。
- React 产品界面，覆盖以上全部流程。
- 私网部署拓扑、健康检查与结构化日志、运行加固、备份恢复演练工具；证据授权下载、孤儿清理与完整性校验。

以上是已交付的代码能力，不代表已在真实试点环境完成部署或开放。受控上线前先完成 [design.md](design.md) 规定的 UI/UX 整理、组件与图标库接入、实际浏览器与用户旅程验证，再进入试点。当前设计基线选用 Ant Design 6 与配套图标，尚待实施。部署运行说明见 [deploy/README.md](deploy/README.md)，阶段安排见 [路线](docs/roadmap.md)。

## 快速开始

要求 Python 3.12+、Node 22.22.0+、Docker Compose；前端使用 `web/package.json` 声明的 npm 版本。

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
cd web && npm ci && npm run typecheck && npm run lint && npm run test && npm run build && npm run test:browser
```

全量 PostgreSQL 测试必须用全新的库：部分多 Session / 并发测试会真实提交数据，bootstrap 测试要求库里没有 Organization，CI 也是每次空库。共享开发库 `easyaudit` 仍用于日常开发和单个测试。

```bash
(
  export PGPASSWORD=easyaudit DATABASE_URL=postgresql+psycopg://easyaudit:easyaudit@localhost:5432/easyaudit_test
  dropdb -h localhost -U easyaudit --if-exists easyaudit_test \
    && createdb -h localhost -U easyaudit easyaudit_test \
    && alembic upgrade head \
    && EASYAUDIT_RUN_POSTGRES_TESTS=1 pytest
)
```

真实 FastAPI + PostgreSQL 浏览器旅程运行方式见 CI 的 `browser-acceptance` job，前端入口为 `npm run test:browser:real`。

## 文档

- [design.md](design.md)：前端设计基线、固定组件/图标、页面与交互规范
- [docs/architecture.md](docs/architecture.md)：架构规则
- [docs/domain.md](docs/domain.md)：领域模型与场景
- [docs/roadmap.md](docs/roadmap.md)：路线
- [docs/adr/](docs/adr/)：架构决策记录
- [AGENTS.md](AGENTS.md)：开发流程与 Agent 分工
- [CONTRIBUTING.md](CONTRIBUTING.md)：贡献与 PR 要求
- [deploy/README.md](deploy/README.md)：部署、运维与备份恢复

## License

尚未选择开源许可证。在许可证明确前，本仓库代码不授予复制、修改或分发许可。

