# 实施路线

## M0.1 — Corrected Bootstrap（当前）

- Python/FastAPI/SQLAlchemy synchronous Session/psycopg 3/PostgreSQL/Alembic 工程底座。
- 修正后的核心概念、关系不变量与历史 ScenarioVersion 寻址。
- 跨场景 ReviewPlan、跨部门 ActionAssignee 与强 FK 持久化规则。
- OpenAPI、容器、自动测试、架构护栏和 CI。

## M1 — Platform Foundation

- Organization、Department、User、账号和登录。
- 平台级权限与业务角色分离。
- 首批 PostgreSQL 领域表、事务和审计基础设施。
- 应用服务、错误契约、OpenAPI 和本地开发容器。
- Activity 持久化为 append-only；业务路径不得 UPDATE/DELETE 历史事件。
- 强制验证 CaseMember、FindingParticipant、ActionAssignee 的 User/Department 与 ReviewCase 属于同一 Organization，并以跨组织拒绝测试作为 M1 验收条件。

## M2 — 过程审查闭环

- 以新模型重建过程审查。
- 策划、执行、发现、整改、验证、关闭的主路径。
- Activity、Submission、附件与通知。

## M3 — 第二场景验证

- 选择与过程审查差异明显的场景。
- 验收新增场景无需复制整套 API/页面。
- 验收核心代码无大量场景条件分支。
