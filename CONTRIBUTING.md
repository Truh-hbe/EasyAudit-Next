# Contributing

开发流程见 [AGENTS.md](AGENTS.md)，架构规则见 [docs/architecture.md](docs/architecture.md)。

## 基本原则

1. Review Core 领域层不依赖 FastAPI、Pydantic、SQLAlchemy、Alembic 或具体数据库。
2. 业务身份通过 `CaseMember`、`FindingParticipant`、`ActionAssignee` 表达，不写进平台账号角色。
3. 新场景通过 Scenario 扩展点接入；核心代码里不出现 `if scenario == ...`。
4. 核心关系使用强外键和组织感知的组合外键，不用 Generic FK。
5. 正式业务动作产生 append-only 的 `Activity`；需要保留原始表达时使用 `Submission`。
6. 架构级变化需要更新 `docs/architecture.md` 或新增 ADR。

## 提交

- 使用 Conventional Commits，例如 `feat(review-core): add finding reopen reason`。
- 提交前至少跑一遍 README 中的验证命令。
