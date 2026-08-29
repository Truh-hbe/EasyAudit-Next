# Contributing

## 基本原则

1. Review Core Domain 不得依赖 FastAPI、Pydantic、SQLAlchemy、Alembic 或具体数据库。
2. 业务身份通过 `CaseMember`、`FindingParticipant` 表达，不写入平台账号角色。
3. ActionItem 的责任与协作主体通过 `ActionAssignee` 表达，不增加单值 `owner_id`。
4. 新场景通过 Scenario 扩展点接入；历史 Case 必须按 `(scenario_key, version)` 精确解释。
5. 不复制整套 API，也不在核心代码堆叠 `if scenario == ...`。
6. 核心数据关系使用强外键；不得把领域 Subject 直接映射成 Generic FK。
7. Activity 的审计不变性由 append-only 持久化保证；禁止业务路径 UPDATE/DELETE 历史事件。
8. 所有资源级参与关系必须拒绝跨 Organization 的 User/Department。
9. 正式业务动作必须能产生 `Activity`；需要保留原始用户表达时使用 `Submission`。
10. 每项架构级改变必须新增或更新 ADR。

## Agent / Codex 开发流程

使用 ChatGPT + Codex 协作开发时，以 `AGENTS.md` 和 `docs/architecture/agent-development-workflow.md` 为执行契约。机器可读阶段状态位于 `.easyaudit/development-state.json`；当其 `active=true` 时，提交前必须通过：

```bash
python scripts/easyaudit_gate.py check
```

请求实现或 Final Review 前生成只读 Review Bundle：

```bash
python scripts/easyaudit_gate.py bundle
```

C2C 本地执行记录仅用于迭代反馈；GitHub Actions 仍是 Final CI 权威。

## 本地验证

验证命令见 README；提交前至少执行架构检查、OpenAPI 检查与测试。

提交信息使用 Conventional Commits，例如：`feat(domain): add review case invariant`。
