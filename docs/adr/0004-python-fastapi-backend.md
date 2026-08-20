# ADR-0004：后端采用 Python/FastAPI 技术路线

- 状态：Accepted
- 日期：2026-08-21

## 决策

EasyAudit-Next 后端采用 Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL 与 Alembic。TypeScript 可用于前端，但不维护第二套 TypeScript 后端领域模型。

## 理由

`EasyAudit_Project` 已积累 Python/FastAPI 工程经验。EasyAudit-Next 当前主要风险是领域重构；同时迁移后端语言会叠加技术栈迁移风险，却没有已证实的收益。统一的 Python 领域模型也避免“TypeScript 与 Python 谁是领域真相”的双重来源问题。

## 后果

- M0.1 即建立 FastAPI、SQLAlchemy、PostgreSQL、Alembic、OpenAPI 与容器底座。
- Review Core Domain 使用纯 Python，不依赖 FastAPI、Pydantic 或 SQLAlchemy。
- M1 在同一 Python 模型和 migration 链上实现 Identity & Organization 与首批领域表。
- 若未来更换后端技术栈，必须以新 ADR 明确迁移收益、范围和领域模型权威来源。
