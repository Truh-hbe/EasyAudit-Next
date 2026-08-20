# 实施路线

## M0 — Bootstrap（当前）

- 核心概念与关系不变量。
- 模块化单体边界与 Scenario 扩展契约。
- 最小 API、自动测试、架构护栏和 CI。

## M1 — Platform Foundation

- Organization、Department、User、账号和登录。
- 平台级权限与业务角色分离。
- PostgreSQL schema、migration、事务和审计基础设施。
- 应用服务、错误契约、OpenAPI 和本地开发容器。

## M2 — 过程审查闭环

- 以新模型重建过程审查。
- 策划、执行、发现、整改、验证、关闭的主路径。
- Activity、Submission、附件与通知。

## M3 — 第二场景验证

- 选择与过程审查差异明显的场景。
- 验收新增场景无需复制整套 API/页面。
- 验收核心代码无大量场景条件分支。
