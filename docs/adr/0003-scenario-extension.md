# ADR-0003：以版本化 Scenario Policy 扩展业务场景

- 状态：Accepted（后果中"`get_latest(key)` 只服务于新 Case"一句已废止：新 Case 显式选择已发布的精确版本，见 [docs/domain.md](../domain.md) 不变量 2；`get_latest` 已删除）
- 日期：2026-08-21

## 决策

Scenario 负责声明场景标识、不可变版本、角色键和输入校验策略。Registry 按 `(scenario_key, scenario_version)` 保存全部历史 Policy；Review Core 不识别“过程审查”等具体场景名称。

## 理由

EasyAudit-Next 的核心目标是从过程审查专用工具演进为通用审查平台。复制整套 API/页面或持续增加场景条件分支，会重新形成多个专用系统的拼接体。

## 后果

- 新场景通过注册 Policy 接入。
- 历史 ReviewCase 使用 `get(key, version)` 精确解释；`get_latest(key)` 只服务于新 Case。
- 已注册版本不得被覆盖或原地修改。
- M3 必须用第二场景验证该边界。
- M0 不引入万能低代码或数据库动态状态机。
