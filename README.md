# EasyAudit-Next

EasyAudit-Next 是面向跨部门协作的通用审查平台。它以审查领域核心为中心，通过 Scenario 承载“过程审查”等不同业务场景；旧版 `EasyAudit_Project` 继续独立维护，本仓库不承担其内部架构兼容义务。

## M0 Bootstrap

当前仓库完成的是 M0 工程底座：

- 冻结九个核心概念的职责边界：`Scenario`、`ReviewPlan`、`ReviewCase`、`Finding`、`ActionItem`、`CaseMember`、`FindingParticipant`、`Activity`、`Submission`。
- 建立 Platform、Review Core、Scenario 三层边界。
- 用可执行契约和测试固定跨场景不变量。
- 提供无外部依赖的最小 API，用于健康检查和工程验证。
- 建立架构决策记录、CI 与贡献约定。

M0 不包含账号登录、持久化、完整状态流转、业务页面，也不引入万能低代码、BPMN、数据库动态状态机、复杂督办实体、知识图谱或无来源 AI 总结。

## 快速开始

要求 Node.js 24+。M0 不需要安装第三方依赖。

```bash
npm run check
npm run start:api
```

API 启动后：

- `GET /health`：存活检查。
- `GET /api/v1/meta/domain-model`：M0 核心概念清单。

## 目录

```text
apps/api/              最小 HTTP 入口；后续承载应用层适配
packages/domain/       无框架、无数据库依赖的 Review Core
docs/architecture/     领域边界与路线说明
docs/adr/              架构决策记录
scripts/               架构护栏
```

下一阶段是 M1：Identity & Organization、PostgreSQL 持久化、应用服务与正式 API 契约。

## License

尚未选择开源许可证。在许可证明确前，本仓库代码不授予复制、修改或分发许可。
