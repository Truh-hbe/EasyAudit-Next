# EasyAudit-Next Agent Guide

面向跨部门协作的通用审查平台。开始改代码前先读：

- [docs/architecture.md](docs/architecture.md)：必须遵守的架构规则（依赖方向、事务与锁顺序、授权、错误语义）
- [docs/domain.md](docs/domain.md)：领域模型与两个场景的生命周期和权限
- [docs/roadmap.md](docs/roadmap.md)：当前要做什么

## 常用命令

```bash
docker compose up -d db
python -m pip install -e ".[dev]"
alembic upgrade head

ruff check . && mypy && python scripts/check_architecture.py && python scripts/check_openapi.py
EASYAUDIT_RUN_POSTGRES_TESTS=1 pytest

cd web && npm ci && npm run typecheck && npm run lint && npm run test && npm run build
cd web && npm run test:browser          # 前端浏览器测试
cd web && npm run test:browser:real     # 需要真实 FastAPI + PostgreSQL，见 CI
```

## 开发流程

1. 从 `main` 拉分支：`feat/…`、`fix/…`、`chore/…`、`docs/…`。
2. 小改动直接做。如果改动涉及领域模型、权限、并发、迁移或新的外部依赖，先在 PR 描述里写几段设计说明：问题、方案、考虑过的替代方案。需要团队长期遵守的规则同步写进 `docs/architecture.md` 或新增 ADR。
3. 验收就是测试，不单独写验收清单文档：
   - 业务规则：单元测试和 API 测试。
   - 持久化和并发：真实 PostgreSQL 集成测试。并发修复必须附带双 Session 竞争测试。
   - 用户旅程：Playwright。
4. 本地跑通上面的检查后开 PR。CI（`check`、`frontend`、`browser-acceptance`）全绿，并经过一次跨厂商 review（见下文）后，由维护者合并。
5. 一个 PR 只做一件事，不要夹带无关重构。

不要新增阶段状态文件、Gate 文档、审查证据包，也不要写"某某不得做"式的长篇契约。规则写进代码、测试和架构检查里，文档只记录结论。

## 多 Agent 分工（Paseo Profile）

同一个工作目录同一时间只允许一个 Agent 写代码。需要并行时，用 `git worktree` 分开。Paseo worktree 按 `paseo.json` 初始化，共用主检出里 `docker compose up -d db` 启动的 PostgreSQL，因此某个分支的迁移会作用到所有 worktree。

| Profile | 模型 | 模式 | 用途 |
|---|---|---|---|
| 总指挥 | Claude Opus 5.5 / high | auto | 任务分解、分派、进度跟踪、最终决策。不直接写代码 |
| 主力实现 | Claude Sonnet 5.5 / medium | auto | 功能实现、测试编写、bug 修复。大多数开发任务 |
| 辅助实现 | Gemini 3.8 Flash High (pi) / high | default | 批量重命名、样板代码、迁移脚本初稿、简单修复。跨厂商 |
| 代码审查 | Codex（GPT）/ high | 只读 | 审 PR diff，重点是并发、授权、跨组织隔离、事务锁。跨厂商 |
| 难题委员会-Fable | Claude Fable 5.1 / xhigh | plan（只读） | 复杂架构设计、疑难 bug 根因分析 |
| 难题委员会-Opus | Claude Opus 5.5 / xhigh | plan（只读） | 与 Fable 组成双人委员会，提供第二视角 |
| 探索 | Claude Haiku 4.5 | plan（只读） | 代码搜索、定位引用、CI 初筛、日志检查、定时任务 |

GPT 系列只用于代码审查，不写代码。

要点：

- 写代码的和 review 的用不同厂商的模型，避免同源的盲点。
- review 结论只是建议。P0/P1 问题要么在 PR 中修复，要么由维护者明确接受风险。
- 换模型或压缩上下文后，重新读取 `git status` 和 PR 状态，不要依赖对话记忆。

## 红线

- 不提交密钥、真实凭证、客户数据或导出文件。本地配置使用 `.env.example` 作为模板。
- 不直接推送 `main`，不强推共享分支，只由人合并 PR。受 GitHub 私有仓库免费套餐限制，`main` 没有服务端分支保护（无法配置 required check），只靠约定保护：任何 Agent 都不能直接 push `main`，所有变更走 PR，且合并前 `check`、`frontend`、`browser-acceptance` 必须全绿，由人合并。
- 部署、访问生产数据、开放真实用户流量都需要维护者当次明确授权。
