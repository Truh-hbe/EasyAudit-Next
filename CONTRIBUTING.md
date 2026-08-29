# Contributing

## 基本原则

1. Review Core Domain 不得依赖 FastAPI、Pydantic、SQLAlchemy、Alembic 或具体数据库。
2. 业务身份通过 CaseMember、FindingParticipant 表达，不写入平台账号角色。
3. ActionItem 的责任与协作主体通过 ActionAssignee 表达，不增加单值 owner_id。
4. 新场景通过 Scenario 扩展点接入；历史 Case 必须按 scenario_key 和 version 精确解释。
5. 不复制整套 API，也不在核心代码堆叠 Scenario identity branches。
6. 核心数据关系使用强外键；不得把领域 Subject 直接映射成 Generic FK。
7. Activity 的审计不变性由 append-only 持久化保证；禁止业务路径 UPDATE/DELETE 历史事件。
8. 所有资源级参与关系必须拒绝跨 Organization 的 User/Department。
9. 正式业务动作必须能产生 Activity；需要保留原始用户表达时使用 Submission。
10. 每项架构级改变必须新增或更新 ADR。

## Web ChatGPT 开发流程

项目开发和 Review 的主控是 Web ChatGPT / GPT-5.6 sol。每个里程碑切片使用独立的 Dev 对话和独立的 Review 对话；本地 Codex / 浏览器负责启动、驱动和收集这两个对话，并执行必要的代码、部署和浏览器测试。

用户不需要手工复制历史摘要、源代码、差异、日志或 SHA。新对话必须先读取 AGENTS.md、项目状态、development-state.json、Gate 文档、当前 PR 和 GitHub CI。

机器可读阶段状态位于 .easyaudit/development-state.json；当 active=true 时，提交前必须通过：

python scripts/easyaudit_gate.py check

请求实现或 Final Review 前生成 Review Bundle：

python scripts/easyaudit_gate.py bundle

Gate 和 Final Review 的结论必须记录在 .easyaudit/review-decision.json 或批准的 GitHub Review 记录中。C2C、浏览器或本地执行结果只能作为过程证据；GitHub Actions 仍是 Final CI 权威。

## 本地验证

验证命令见 README；提交前至少执行架构检查、OpenAPI 检查与测试。

提交信息使用 Conventional Commits，例如：feat(domain): add review case invariant。