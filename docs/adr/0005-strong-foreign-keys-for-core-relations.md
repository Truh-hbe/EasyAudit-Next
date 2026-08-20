# ADR-0005：核心关系必须使用强外键

- 状态：Accepted
- 日期：2026-08-21

## 决策

ReviewPlan、ReviewCase、Finding、ActionItem、Submission、Activity 目标以及 User/Department 参与关系，在 PostgreSQL 中必须映射为可验证的真实外键。禁止将核心关系实现为无数据库完整性约束的 `entity_type + entity_id` Generic FK。

## 理由

Generic FK 便于快速扩展，但数据库无法验证目标存在、级联规则和租户边界。审查记录属于需要长期留痕的数据，引用失真会直接破坏审计可信度。

## 后果

- Activity 的领域 `subject` 是封闭联合类型，不代表持久化表使用 Generic FK。
- M1 可选用类型化可空外键加 Check Constraint，或按目标类型建立关联表。
- FindingParticipant 与 ActionAssignee 的 User/Department 主体必须分别对应受约束外键。
- 仅非关键辅助关系可在单独 ADR 论证后采用通用引用。

## M1 组织边界完整性验收

外键只能证明目标存在，不能单独证明目标与 ReviewCase 属于同一 Organization。M1 必须拒绝以下关系中的跨组织主体：

```text
CaseMember.user.organization_id
  = CaseMember.review_case.organization_id

FindingParticipant.user_or_department.organization_id
  = FindingParticipant.finding.review_case.organization_id

ActionAssignee.user_or_department.organization_id
  = ActionAssignee.action_item.finding.review_case.organization_id
```

具体实现可在 M1 模型设计时从应用服务校验、组合外键、Check/Trigger 或其组合中选择，但必须满足：

- 所有写入入口执行同一组织边界规则。
- User 与 Department 两种主体均有正向和跨组织拒绝测试。
- 直接 repository 写入与批量操作不得绕过边界。
- 跨组织引用测试必须进入 CI，未满足时 M1 不得验收。
