# OMP Agent Control Plane Hardening

## Gate status

本文定义独立的过程完整性切片：

```text
Process — OMP Agent Control Plane Hardening
```

该切片用于约束本项目中的 **OMP Agent**。项目文档、用户界面、Skill、Prompt、Extension 与证据均不得再将该角色称为 Pi Agent；底层运行时兼容性不改变项目角色名称。

本 Gate Draft 仅允许修改状态、Roadmap 与本 Gate 文档。它不授权实现 `.omp/**`、修改 `AGENTS.md`、修改 Gate 脚本、修改 CI，也不授权任何产品代码、部署或流量。

## 1. 触发原因

M6-Ops 实施期间出现了可重复验证的控制失效：

1. OMP Agent 在多轮上下文压缩后偏离任务，未能按固定 Candidate 与 Gate 推进；
2. `FINAL_REVIEW` 已被冻结后仍出现 executable 工作区修改；
3. failed exact-head CI 未阻止状态提前进入 `FINAL_REVIEW`；
4. 为修复浏览器竞态，Agent 曾把“恰好两次 GET”放宽为“至少两次”，可能掩盖 Gate 明确禁止的第三次自动请求；
5. 两个 OMP Session 同时操作一个工作区，其中一个 Session 在另一个 Session 诊断期间提交并继续修改 state；
6. 当前 Gate check 没有拒绝 `FINAL_REVIEW` 下的脏 executable 工作区；
7. 网页端 GitHub Connector 曾在 Draft → Ready 操作上失败，需要本地 `gh` 降级，但降级规则只存在于对话中；
8. OMP Agent 曾建议跳过 Roadmap 前置条件，使 M6-Ops implementation 在 M6.1b 之前启动。

这些不是产品领域缺陷，而是 Agent 控制面缺失。继续依赖对话记忆会重复产生同类问题。

## 2. 目标

该切片必须将以下机制从聊天约定升级为版本化、可测试、可阻断的项目能力：

```text
常驻规则
+ 每轮动态状态注入
+ 单工作区写租约
+ phase/scope 工具阻断
+ 独立证据核验
+ GitHub Connector 降级
+ 单状态转换提示词编排
+ CI/脚本最终兜底
```

目标不是让 OMP Agent 自治合并或部署，而是确保它在每次交互中：

- 先识别当前状态与合法下一动作；
- 不把外部 Agent 的文字声明当成事实；
- 不跨 Scope、跨 Phase 或跨 Roadmap 前置条件；
- 不与另一 OMP Session 并发写同一工作区；
- 在连接器失败时只切换执行通道，不降低授权标准；
- 在上下文压缩、恢复、切换模型或新会话后重新建立控制上下文；
- 失败时 fail-closed，而不是继续猜测或扩大工作范围。

## 3. 权威边界

权威顺序保持不变：

```text
Repository Gate / Architecture / Acceptance
  -> GitHub exact-head state and required CI
  -> Human Maintainer authorization
```

OMP Agent 是本地执行、验证和证据编排者，不获得以下权力：

- 自行批准 Gate；
- 自行消除 P0/P1；
- 以本地结果替代 exact-head GitHub CI；
- 推断用户已经授权 merge/deploy/secret access/traffic；
- 因网页 Connector 故障而绕过 GitHub 状态；
- 修改业务 Roadmap、领域真相或并发模型而不经过独立 Gate。

网页端 ChatGPT 可继续承担架构、实现和 Review，并可通过 GitHub Connector 写入仓库；其返回的 PR、SHA、CI 与合并状态对 OMP Agent 而言仍是“待核验声明”。

## 4. 分层控制模型

### 4.1 常驻规则：`AGENTS.md`

实施阶段必须补充一个简洁的 Per-turn Control Protocol。每个请求先分类为：

```text
READ_ONLY
PLAN
MUTATE
REVIEW
MERGE
DEPLOY
```

分类决定强制前置动作。规则必须明确：

- READ_ONLY 不等于相信外部声明；
- PLAN 必须检查 Roadmap 依赖；
- MUTATE 必须完成 preflight；
- REVIEW 必须针对固定 Candidate；
- MERGE 必须有 `MERGE_AUTHORIZED`、exact-head CI 与人类授权；
- DEPLOY 必须有独立环境 Gate 与操作员授权。

`AGENTS.md` 保持规范性和简洁性；详细运行手册放入 Project Skill。

### 4.2 运行手册：Project Skill

项目必须提供：

```text
.omp/skills/easyaudit-control-plane/SKILL.md
```

Skill 的触发描述应覆盖 EasyAudit-Next 中的规划、修改、Review、合并、部署、GitHub 核验和故障恢复。正文包含：

- mandatory startup sequence；
- phase-specific checklist；
- candidate/control 分离；
- 本地与 GitHub 证据核验；
- Connector 降级；
- 并发 Session 处理；
- compaction/new/resume 后恢复；
- Prompt 编排规范；
- 禁止事项与停止条件。

Skill 自动触发不能作为强保证。关键摘要必须由 Extension 每轮注入；用户仍可通过 `/skill:easyaudit-control-plane` 显式加载完整手册。

### 4.3 标准操作：Prompt Templates

项目必须提供至少：

```text
.omp/prompts/ea-status.md
.omp/prompts/ea-gate-draft.md
.omp/prompts/ea-gate-review.md
.omp/prompts/ea-address-findings.md
.omp/prompts/ea-final-review.md
.omp/prompts/ea-merge.md
.omp/prompts/ea-next.md
```

每个 Prompt 只推动一个外层状态转换，并包含：

- 当前仓库、PR、base/head/candidate；
- 当前 phase；
- 允许动作；
- 禁止动作；
- 返回证据格式；
- 明确停止条件。

禁止把“实现、Review、授权、合并、post-merge”组合成一个不可中断的 Prompt。

### 4.4 强制执行：Project Extension

项目必须提供项目级 OMP Extension。建议结构：

```text
.omp/extensions/easyaudit-guard/
  index.ts
  state.ts
  lease.ts
  guards.ts
  prompts.ts
```

实现应使用运行时导出的 `CONFIG_DIR_NAME` 或等价机制，不把上游 `.pi` 目录硬编码到项目逻辑。当前项目资源目录是 `.omp`。

Extension 必须在 `before_agent_start` 对每次用户交互注入短小、动态的控制快照，而不是依赖历史上下文：

```text
phase
branch
HEAD
base
candidate
working-tree state
lease owner
Gate check result
allowed next action
remote evidence freshness
```

快照必须明确外部 GitHub 声明是否已独立验证。

### 4.5 最终权威：脚本、CI 与分支保护

Extension 可被禁用、未加载或发生缺陷，因此最终门禁仍由：

- `scripts/easyaudit_gate.py`；
- tooling tests；
- GitHub required checks；
- branch protection；
- expected-head merge；
- 人类授权；

共同承担。

Control Plane 不得把安全性建立在“OMP Agent 通常会听话”之上。

## 5. 单工作区写租约

### 5.1 租约目标

同一 EasyAudit 工作区在任一时刻最多只能有一个具备写权限的 OMP Session。只读 Session 可以并存，但不得执行 edit/write、提交、状态推进或 push。

### 5.2 租约身份

租约至少记录：

```text
schema_version
repository_realpath
session_id
session_file (若可用)
pid
hostname
branch
acquired_at
heartbeat_at
mode = read-only | writer
```

租约不得包含 Prompt、凭据、Cookie、Token、客户数据或文件内容。

### 5.3 获取与失效

- writer 租约必须通过原子创建/替换协议获取；
- 已有活跃 writer 时，后来的 Session 默认降级为 read-only 并明确告警；
- 同主机 PID 存活且 heartbeat 新鲜时，不得自动抢占；
- stale lease 必须同时满足超时和 owner 不存活/不可验证条件，才能进入人工确认的恢复流程；
- Session shutdown 必须尽力释放自己的租约；
- 崩溃后通过 TTL + owner 核验恢复；
- 不得仅因租约文件时间较旧就静默删除；
- 用户显式 takeover 必须留下本地过程证据，但不能替代 GitHub merge/deploy 授权。

租约运行文件必须位于 Git 忽略的项目运行目录，不能污染 Gate working-tree evidence。

## 6. 每轮 Preflight

Extension 每轮至少执行轻量检查：

1. 定位 Git root；
2. 读取并验证 development state；
3. 检查当前 branch/HEAD；
4. 检查 working tree；
5. 检查 writer lease；
6. 在 mutation 前运行 Gate check；
7. 解析 phase、scope、forbidden paths 和 next action；
8. 生成动态控制快照。

网络 fetch 不要求每轮执行。涉及 PR、Review、CI、merge 或外部 GPT 声明时，必须执行有时效标记的 `git fetch`/`gh` 核验。

Preflight 无法完成时：

```text
READ_ONLY may continue with explicit degraded-state warning
MUTATE / MERGE / DEPLOY must fail closed
```

## 7. 工具调用防护

### 7.1 `edit` / `write`

在 active Gate 下，Extension 必须在工具执行前：

- 规范化并解析真实目标路径；
- 拒绝 repository root 外路径；
- 拒绝 `forbidden_paths`；
- 拒绝不匹配 `allowed_paths` 的路径；
- 拒绝 candidate 固定后的非 finalization 文件；
- 拒绝没有 writer lease 的修改；
- state/Gate 无法解析时 fail-closed。

### 7.2 `bash`

Shell 无法仅靠字符串匹配获得完整语义安全，因此采用防御纵深：

- 阻止明确的 merge、push、deploy、secret、破坏性 Git 和状态绕过命令；
- 对高风险命令要求 phase 与人类确认；
- 每次 shell 可能改变 Git 状态后使 preflight 失效；
- 下一次 mutation 前重跑 Gate check；
- CI 对最终 diff 和 phase 做权威验证。

不得声称 bash 拦截可以替代容器隔离或 GitHub 保护。

### 7.3 Merge 与部署

Merge 防护至少要求：

```text
phase == MERGE_AUTHORIZED
PR non-Draft and mergeable
reviewed candidate/control relation valid
required CI green on exact PR head
explicit current human authorization
expected-head protection
```

部署、secret access、restore rehearsal 与 traffic 必须依赖独立 Gate 的明确授权。Control Plane 不提供一键绕过。

## 8. Candidate、Control 与工作区完整性

现有协议继续生效：

```text
C = executable fixed_head 或 docs_review_head
S = state-only control head
W = uncommitted working tree
```

Control Plane 必须新增或加强以下拒绝条件：

- `FINAL_REVIEW`/`MERGE_AUTHORIZED` 下存在任何工作区修改；
- executable Candidate 固定后出现非 finalization commit；
- docs-only reviewed head 后出现非 state-only commit；
- Candidate CI 失败后仍继续 Final Review；
- state 的 phase、fixed head、PR metadata 与 GitHub 状态矛盾；
- Review Bundle 对应旧状态、旧 HEAD 或脏工作区；
- test-only 修复弱化已冻结 Acceptance。

Gate check 与 bundle 必须在必要时支持 `--require-clean`，并在 Final Review 自动路径中成为必选条件。

## 9. 外部声明与证据核验

OMP Agent 必须把以下内容视为声明而非事实：

```text
网页 ChatGPT 返回的 SHA
PR 状态
CI 状态
Draft/Ready 状态
merge result
main HEAD
post-merge parent relation
```

核验至少使用：

- `git fetch`；
- `git rev-parse` / `git diff` / `git merge-base`；
- `gh pr view` / `gh pr checks` / `gh run view`；
- Gate check 与 Review Bundle；
- 必要的本地测试。

核验结果应以结构化摘要返回，不得只回复“看起来正确”。

## 10. GitHub Connector 降级

固定降级顺序：

```text
网页 ChatGPT GitHub Connector
  -> OMP Agent 使用 gh CLI 执行机械操作
  -> 人工 GitHub UI
```

降级只改变执行通道，不改变授权：

- Draft → Ready 可由 OMP Agent 在核验后机械执行；
- Connector 返回错误后必须重新读取 GitHub 状态；
- OMP Agent 不得因为 Connector 故障自行授权 merge；
- merge 仍需 current human authorization、exact-head CI 与 expected-head；
- post-merge 必须核验 main、merge parent、tree 与 PR 状态。

## 11. 上下文压缩和会话恢复

以下事件之后必须重新建立动态控制上下文：

```text
session_start
/new
/resume
/fork
/clone
/reload
manual or automatic compaction 后的下一轮
model change 后的下一轮
```

Extension 每轮注入使流程不依赖 compaction summary。Skill 与 `AGENTS.md` 仍作为完整规范来源。

压缩摘要不得成为 phase、SHA、CI 或授权的权威来源。

## 12. OMP 命令面

实施至少提供：

```text
/ea-status      当前状态、租约、branch/head、合法下一动作
/ea-preflight   强制运行本地 preflight
/ea-verify      核验指定 PR/candidate/CI
/ea-bundle      生成并验证 Review Bundle
/ea-next        生成仅推动一个状态转换的下一条 Prompt
```

命令输出不得包含 Secret，并应在非交互/RPC 模式下有确定行为。

`/ea-next` 只生成 Prompt，不自动发送给网页 ChatGPT，不自动推进 state，也不自动 merge。

## 13. 实施分期

### 13.1 实施观察阶段

Implementation 首先允许 Extension 以 observe 模式运行：

- 每轮注入状态；
- 显示状态 Widget；
- 记录将被阻止的操作；
- 运行测试矩阵；
- 不静默改变工具参数。

### 13.2 强制阶段

Final candidate 必须默认启用 enforce 模式：

- 无 writer lease 的 mutation 被阻止；
- scope/phase 违规被阻止；
- merge/deploy 未授权被阻止；
- preflight 失败时 mutation fail-closed。

Observe 不能作为最终交付状态。

## 14. 实施范围建议

Gate 通过后的 executable implementation 可申请以下范围：

```text
AGENTS.md
.omp/skills/easyaudit-control-plane/**
.omp/prompts/**
.omp/extensions/easyaudit-guard/**
.gitignore
scripts/easyaudit_agent.py
scripts/easyaudit_gate.py
tests/tooling/**
.github/workflows/**
docs/architecture/agent-development-workflow.md
.easyaudit/development-state.json
```

具体 allowlist 必须在进入 IMPLEMENTATION 的 state-only 转换中精确列出；此处不是提前授权。

不得修改：

```text
src/**
alembic/**
openapi/**
web/**
Dockerfile*
compose*
deploy/**
业务 Gate / Acceptance 真相
```

## 15. 非目标

本切片不实现：

- 产品功能；
- Review Core/Scenario 修改；
- M6.1b 私网基础设施；
- M6-Ops 产品实现或合并；
- 自动替用户批准 Gate/merge/deploy；
- 自动访问 Secret；
- 远程强制终止网页 ChatGPT；
- 解析任意 shell 命令的完整语义；
- 用 Agent Extension 替代 CI、branch protection 或人类维护者。

## 16. Roadmap 关系

该过程切片是一次完整性 interlock：

```text
M6.1a complete
  -> Process OMP Agent Control Plane Hardening
  -> M6.1b
  -> resume/rebase M6-Ops implementation
```

当前 Draft PR 不修改或合并停放中的 M6-Ops PR。Control Plane 完成后，M6.1b 仍必须先于 M6-Ops Final Review/merge。

## 17. 生命周期

本 Gate Draft 使用 docs-only 生命周期：

```text
GATE_DRAFT
  -> GATE_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED + active=false
```

Gate 合并后，Control Plane implementation 必须创建独立 executable PR：

```text
IMPLEMENTATION
  -> FINAL_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED + active=false
```

任何阶段都不得把 Gate Review PASS 误报为 executable implementation 完成。
