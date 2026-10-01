# Contributing

开发流程见 [AGENTS.md](AGENTS.md)，架构规则见 [docs/architecture.md](docs/architecture.md)，前端设计与组件/图标规范见 [design.md](design.md)。当前阶段见 [docs/roadmap.md](docs/roadmap.md)。

## 基本原则

1. Review Core 领域层不依赖 FastAPI、Pydantic、SQLAlchemy、Alembic 或具体数据库。
2. 业务身份通过 `CaseMember`、`FindingParticipant`、`ActionAssignee` 表达，不写进平台账号角色。
3. 新场景通过 Scenario 扩展点接入；核心代码里不出现 `if scenario == ...`。
4. 核心关系使用强外键和组织感知的组合外键，不用 Generic FK。
5. 正式业务动作产生 append-only 的 `Activity`；需要保留原始表达时使用 `Submission`。
6. 架构级变化需要更新 `docs/architecture.md` 或新增 ADR。
7. 前端先使用设计规范指定的组件、图标与 token；业务封装保持轻量，权限和生命周期以后端为准。

## 提交

- 使用 Conventional Commits，例如 `feat(review-core): add finding reopen reason`。
- 提交前至少跑一遍 README 中的验证命令。
- 前端实现 PR 更新有变化的用户旅程测试，在描述中附关键页面的前后截图与浏览器验证结果；设计规则变化同步更新 `design.md`。
- 文档 PR 核对引用、路径与当前能力表述；文档写明的待实现事项不能标记为已交付代码能力。
- 受 GitHub 私有仓库免费套餐限制，`main` 无服务端分支保护，严禁直接推送；所有变更走 PR 且在 CI 全绿后由人工合并，详见 [AGENTS.md](AGENTS.md)。
