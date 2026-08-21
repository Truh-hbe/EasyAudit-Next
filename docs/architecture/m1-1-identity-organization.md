# M1.1 Identity & Organization Persistence

M1.1 只持久化平台身份与组织结构，不开放管理 API，也不引入认证、Scenario 或 Review Core 表。

## 领域边界

`easyaudit_next.platform.domain` 是 Organization、Department、User 与 PlatformRole 的唯一领域定义。Review Core 引用平台身份，不拥有另一套人员或组织模型。

第一版关系保持克制：

```text
Organization
├── Department tree
└── User
    └── optional primary Department
```

User 不支持多部门 membership。后续跨部门业务协作继续由 CaseMember、FindingParticipant 和 ActionAssignee 表达。

## PostgreSQL 完整性

主键均为应用侧生成的 UUIDv4。`departments` 和 `users` 除主键外，额外声明 `(id, organization_id)` 唯一键，以便后续业务表使用组织感知的组合外键。

当前 M1.1 已使用该模式保护：

- Department 的 parent 必须属于同一 Organization。
- User 的 primary Department 必须属于同一 Organization。
- Department 不得以自身或任何后代作为 parent；应用服务与 PostgreSQL trigger 双重拒绝循环。
- PlatformRole 只允许 `system_admin` 与 `ordinary_user`。
- 名称与显示名不得为空，也不得带首尾空白。

跨 Organization 可以开展未来的业务协作设计讨论，但数据库关系不得把另一个 Organization 的主体挂入当前组织对象。

## 事务边界

Application Service 不自行 commit。SQLAlchemy repository 使用调用方提供的同步 Session，并在写入时 flush，让数据库约束错误发生在当前事务内。Web 请求、CLI 与测试均应通过 `session_scope` 或等价的单一同步事务边界调用服务。

## M1.1 明确不包含

- LocalCredential、密码散列、AuthSession 与 Cookie。
- 管理 API 与完整前端。
- Scenario 持久化。
- ReviewPlan、ReviewCase、Finding、ActionItem 等 Review Core 持久化。
- 多部门 User membership、Team、LDAP、OIDC 与 MFA。
