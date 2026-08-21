# EasyAudit-Next

EasyAudit-Next 是面向跨部门协作的通用审查平台。它以 Review Core 为中心，通过版本化 Scenario 承载“过程审查”等不同业务场景；旧版 `EasyAudit_Project` 继续独立维护，本仓库不承担其内部架构兼容义务。

## M1.1 Platform Foundation

M0.1 保留 M0 的领域成果，并完成合并前架构校正：

- 正式确定后端技术栈为 Python 3.12、FastAPI、SQLAlchemy 2 synchronous Session、psycopg 3、PostgreSQL 与 Alembic；TypeScript 留给前端，不建立双后端领域模型。
- 冻结 `Scenario`、`ReviewPlan`、`ReviewCase`、`Finding`、`ActionItem`、`CaseMember`、`FindingParticipant`、`ActionAssignee`、`Activity`、`Submission` 的职责边界。
- Scenario Registry 按 `(scenario_key, scenario_version)` 保存和寻址，不允许新版覆盖历史版本。
- ReviewPlan 是跨 Scenario 的策划容器；Scenario 及其版本属于 ReviewCase。
- FindingParticipant 与 ActionAssignee 支持 User、Department，并允许主责与协作主体并存。
- Activity 使用类型化领域 Subject；未来数据库必须使用强外键和 append-only 写入，不得照搬 Generic FK。
- 提供 FastAPI、运行时 OpenAPI、SQLAlchemy、Alembic、PostgreSQL Compose、容器、测试与 CI 底座。

M0.1 不包含账号登录、首批正式领域表、完整状态流转或业务页面，也不引入万能低代码、BPMN、数据库动态状态机、复杂督办实体、知识图谱或无来源 AI 总结。

M1.1 在该基线上新增：

- Organization、Department tree 与 User 的纯 Python Platform Domain。
- 应用侧 UUIDv4 身份、同步 Application Service 与 SQLAlchemy repository。
- `organizations`、`departments`、`users` 第一份正式 PostgreSQL migration。
- 组织感知的组合外键，数据库直接拒绝跨 Organization 的部门父级与用户主部门。
- 部门循环的服务层校验与 PostgreSQL trigger 保护。
- PostgreSQL migration、repository round-trip 和完整性集成测试。

M1.1 仍不包含登录、Credential、Session、管理 API、Scenario 持久化或 Review Core 持久化。

## 快速开始

要求 Python 3.12+ 与 Docker Compose。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d db
alembic upgrade head
uvicorn easyaudit_next.main:app --reload
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

验证：

```bash
ruff check .
mypy
python scripts/check_architecture.py
python scripts/check_openapi.py
pytest
```

API 启动后：

- `GET /health`：存活检查。
- `GET /api/v1/meta/domain-model`：M0.1 核心概念清单。
- `GET /docs`：Swagger UI。
- `GET /openapi.json`：FastAPI 生成的 OpenAPI 3.1 契约。

## 目录

```text
src/easyaudit_next/api/                 HTTP 适配与 API 契约
src/easyaudit_next/platform/            身份、组织等平台能力的边界
src/easyaudit_next/review_core/domain/  无框架、无 ORM 依赖的 Review Core
src/easyaudit_next/infrastructure/      SQLAlchemy 与外部基础设施适配
alembic/                                数据库 migration 链
openapi/                                稳定操作契约基线
docs/                                   领域模型、路线与 ADR
tests/                                  API 与领域边界测试
```

下一阶段是 M1.2：Authentication & Platform Authorization。

## License

尚未选择开源许可证。在许可证明确前，本仓库代码不授予复制、修改或分发许可。
