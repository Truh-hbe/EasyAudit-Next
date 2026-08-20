# Contributing

## 基本原则

1. 核心领域不得依赖 Web 框架、ORM 或具体数据库。
2. 业务身份通过 `CaseMember`、`FindingParticipant` 表达，不写入平台账号角色。
3. 新场景通过 Scenario 扩展点接入，不复制整套 API，也不在核心代码堆叠 `if scenario == ...`。
4. 正式业务动作必须能产生 `Activity`；需要保留原始用户表达时使用 `Submission`。
5. 每项架构级改变必须新增或更新 ADR。

## 本地验证

```bash
npm run check
```

提交信息使用 Conventional Commits，例如：`feat(domain): add review case invariant`。
