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
generation_nonce
acquired_at
heartbeat_at
mode = read-only | writer
```

租约不得包含 Prompt、凭据、Cookie、Token、客户数据或文件内容。

### 5.3 获取与失效

- writer 租约必须通过原子创建/替换协议获取；
- 每次成功获取生成不可预测且唯一的 `generation_nonce`；
- heartbeat、release 与 takeover 必须同时比较 owner identity 和 generation，避免旧 owner/ABA 删除新租约；
- 已有活跃 writer 时，后来的 Session 默认降级为 read-only 并明确告警；
- 同主机 PID 存活且 heartbeat 新鲜时，不得自动抢占；
- stale lease 必须同时满足超时和 owner 不存活/不可验证条件，才能进入人工确认的恢复流程；
- Session shutdown 必须尽力释放自己当前 generation 的租约；
- 崩溃后通过 TTL + owner + generation 核验恢复；
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

### 6.1 Development-state transition validator

`.easyaudit/development-state.json` 是策略根，不得通过通用 edit/write/bash 自行修改。所有 state 变化必须经专用 `ea_transition` adapter：

```text
read committed old state from HEAD + working tree
  -> construct proposed state from a typed transition request
  -> validate old -> proposed
  -> re-prove Git/GitHub preconditions required by target phase
  -> atomically write proposed state
  -> run Gate check
```

validator 至少强制：

- 只允许状态机定义的相邻转换或显式 rollback 转换；
- rollback 必须清空无效 candidate，并写入 bounded reason；
- 普通 transition 不得改变 project、slice、base、work branch、PR 或 candidate kind；
- `allowed_paths` 不得扩大、`forbidden_paths` 不得削弱、`finalization_allowed_paths` 不得扩大；
- Scope 变化只能发生在一个独立审查过的 bootstrap/rebaseline transition，并由当前 Gate 的机器策略允许；
- `docs_review_head`/`fixed_head` 必须解析、满足 ancestry，并与 candidate kind/phase 一致；
- 进入 `GATE_REVIEW` 必须有 docs candidate/control 证明；
- 进入 `FINAL_REVIEW` 必须 clean、current Bundle、完整本地 required evidence 与固定 executable candidate；
- 进入 `MERGE_AUTHORIZED` 必须重新获取 authoritative required-check set，并证明 exact PR head 全绿、Review finding 为零且具备当前人类授权动作；
- 进入 `MERGED` 只能用于 post-merge rebaseline，并验证 main/merge parent/PR merged；
- validator 失败时不得产生部分 state 写入。

通用文件工具必须把 development-state 和机器策略文件视为 protected paths。即使持有 writer lease，也只能由专用 typed adapter 修改。

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

### 7.2 Model-facing `bash`

Shell 是否写盘不能通过字符串可靠判断。`python -c`、`tee`、`cp`、重定向和任意脚本都可绕过路径规则，因此：

```text
无有效 writer lease
  -> 阻止所有 model-facing bash
  -> 阻止所有 mutating tools（包括动态发现的 ast_edit 等）
  -> 仅开放专用 read-only status/diff/verify 工具
```

持有 writer lease 时也不得开放可任意写策略根的无约束 shell。active Gate 下的 Agent 命令执行必须通过 `ea_exec` 的版本化 command profiles：

- read-only Git/status/diff/gh verify；
- Gate/architecture/test/build 等审核过的项目命令；
- 明确的 Git add/commit/push adapter；
- 每个 profile 使用 argv/受控参数，不接受任意 shell 拼接；
- profile 声明是否可能修改工作区，执行后使 preflight 失效并重新核验；
- 任何 profile 都不得直接写 development-state 或 workflow policy。

未匹配 profile 的 model-facing bash 在 active Gate 下默认阻止。若未来要开放 sandboxed shell，必须通过单独 Gate 证明文件系统保护，不能靠字符串 denylist。

不得声称该机制替代容器隔离或 GitHub 保护。

### 7.3 OMP `!cmd`、RPC 与非交互执行面

Model tool `bash` 的 `tool_call` 拦截不自动覆盖用户 `!cmd` 或宿主 RPC bash。Control Plane 必须进行 runtime capability negotiation：

- TUI `!cmd` 必须通过 `user_bash` hook 路由到同一 lease/phase guard；
- RPC host 必须证明直接 bash/user-bash 被禁用或经过等价 guard；
- JSON/print/无 UI 模式只允许安全 read-only status/diff/verify；
- 无法证明执行面受控的运行模式，对 mutation/transition/merge/deploy 一律 NO-GO；
- 启动 Widget/status 必须显示当前 mode 为 `protected-write` 或 `read-only-no-go`，不能静默假装受保护。

用户直接在 Extension 外打开普通终端不属于 Agent 防护面，仍由 Git/CI/branch protection 兜底；文档不得扩大声明。

### 7.4 Merge 与部署

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

### 7.5 单次人类授权能力

“当前人类授权”必须是不可继承的一次性能力，而不是聊天文本或 state 字段：

- 只有当前受保护运行时中的阻塞式 human UI challenge/confirmation 可以产生；
- challenge 必须显示 action、repository、PR/environment、exact head/release identity 和随机 nonce；
- C2C、网页 ChatGPT 声明、历史消息、compaction summary、state 或 Agent 自己不能产生能力；
- 无 UI、超时、取消或 identity 漂移均不产生能力；
- 能力只存在内存，绑定一个 exact action 与当前 turn/tool invocation；
- action 成功、失败、取消或 turn 结束后立即失效；
- `/new`、`/resume`、`/fork`、`/clone`、`/reload`、compaction 和进程重启均不继承；
- 最安全的实现是 `ea_authorized_merge` / `ea_authorized_deploy` 在一次受保护调用内完成重新核验、human challenge、执行和失效，不暴露可复用 token。

MERGE/DEPLOY 必须同时满足 phase、remote evidence、exact identity 和该单次能力。

## 8. Candidate、Control 与工作区完整性

现有协议继续生效：

```text
C = executable fixed_head 或 docs_review_head
S = state-only control head
W = uncommitted working tree
```

Control Plane 必须新增或加强以下拒绝条件：

- `FINAL_REVIEW`/`MERGE_AUTHORIZED` 下存在任何工作区修改；
- 通用工具尝试修改 development-state 或 workflow policy；
- proposed state 未通过 old-state → new-state transition validator；
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

### 9.1 机器化 Roadmap predecessor policy

Roadmap Markdown 只供人类解释，不能作为执行授权解析源。前置 policy-seed PR 必须按 §9.3 新增受保护、版本化的，后续 Implementation 只能从 base 读取：

```text
.easyaudit/workflow-policy.json
```

policy 至少把 slice identifier 映射到 predecessor slice identifier，并定义 completion 证明规则。该文件不能由普通 milestone Scope 修改；变更它需要独立 process Gate。

Preflight 必须从受信 `main` Git 历史中找到 predecessor 的 post-merge state commit，验证该 commit 中：

```text
slice == required predecessor
phase == MERGED
active == false
```

并证明 completion commit 是当前 `base.sha` 和工作分支 HEAD 的祖先。仅在 state 中填写一个 SHA、仅在 Roadmap 写 Completed、或仅由 Agent 声称完成均无效。

真实回归固定为：M6-Ops 的 policy predecessor 包含 M6.1b；在 M6.1b completion commit 成为 rebaselined base/main 的祖先之前，PLAN、MUTATE、`/ea-next`、FINAL_REVIEW 和 merge 全部阻止。

### 9.2 Authoritative required-check contract

required CI set 不得由 Agent 猜测。Control Plane 使用一个明确权威源：

1. 优先读取 GitHub branch protection/ruleset 的 required checks，并记录 fetch time/branch/revision；或
2. 当仓库 API 权限无法读取 ruleset 时，读取 candidate base/main 中已受信的 `.easyaudit/workflow-policy.json` exact required-check contract；bootstrap seed 自身只能读取已合并 Gate 的 candidate-external fixed contract。

本项目初始 contract 必须精确列出当前 required jobs，并由 CI 验证这些 job 仍存在于唯一工作流 `.github/workflows/ci.yml`。workflow-policy 不能与被审查产品 Slice 在同一普通 Scope 内一起改写以自我放行。

无法读取权威源、required set 为空、check 缺失、pending、cancelled、skipped（除 contract 明确允许）或 head 不一致时只能返回：

```text
remote evidence unavailable/stale or NO-GO
```

不得 PASS。

### 9.3 Bootstrap trust anchor

任何 proposed/current candidate policy 都不得授权创建或修改它的同一个 candidate。首次上线必须拆成三个独立信任阶段：

```text
A. reviewed docs-only Gate merged to trusted main
  -> B. policy-seed PR adds only exact reviewed policy + state
  -> policy seed merged to trusted main
  -> C. Control Plane implementation based on seeded main
```

#### A. Candidate-external canonical bootstrap contract

本 Gate 合并后的文档是 policy-seed PR 的 candidate-external authority。初始 policy 的语义内容固定为：

```json
{
  "schema_version": 1,
  "policy_id": "easyaudit-workflow-policy-v1",
  "required_checks": {
    "main": {
      "source": "versioned-contract",
      "contexts": ["check", "frontend", "browser-acceptance"]
    }
  },
  "slice_predecessors": {
    "M6.1b-private-infrastructure-qualification": [
      "M6.1a-recovery-contract-tooling",
      "process-omp-agent-control-plane-implementation"
    ],
    "M6-ops-operational-readiness": [
      "M6.1b-private-infrastructure-qualification"
    ]
  },
  "protected_paths": [
    ".easyaudit/development-state.json",
    ".easyaudit/workflow-policy.json"
  ],
  "policy_change_protocol": "separate-reviewed-policy-seed"
}
```

使用 UTF-8、递归 key 排序和 compact separators `(',', ':')` 的 canonical JSON SHA-256 必须为：

```text
31e7c9d4aa8b9f61c20b1d95b85f948ceb919d1d91938c80c5b2006748780857
```

#### B. Policy-seed PR

Gate 合并后先创建独立 slice：

```text
process-omp-agent-control-plane-policy-seed
```

该 PR 只能改变：

```text
.easyaudit/workflow-policy.json
.easyaudit/development-state.json
```

它不得修改 validator、Extension、Skill、Prompt、测试、CI、Gate 文档或任何产品文件。其 Final Review/MERGE_AUTHORIZED 不得读取 proposed policy 为自己授权；必须根据已在 base/main 中的本 Gate 文档、上述固定 hash、base/main 原有 `.github/workflows/ci.yml` 和外部 `gh` check evidence，证明 exact PR head 上：

```text
check = success
frontend = success
browser-acceptance = success
```

若 Gate 文档不在 base ancestry、hash 不匹配、diff 超出两条路径、任一 check 无法获取或不成功，则 seed NO-GO。GitHub rules API 为 403 不允许回退到 proposed policy，只能使用 base/main 已合并 Gate 的 exact bootstrap contract；二者都不可用时 NO-GO。

Seed 合并进入 main 后，policy 才成为 trusted policy root。

#### C. Control Plane implementation PR

Control Plane implementation 必须以包含 seed completion 的 main 为 base，并证明 seed commit 是 base/HEAD ancestor。Implementation allowlist 必须排除 `.easyaudit/workflow-policy.json`，因此 candidate 不能修改 required checks 或 predecessor 来批准自己。

Implementation 可按 Gate 修改 `.github/workflows/ci.yml`，但 required check identity 始终来自 base 中已信任 policy；若 candidate 删除/重命名 required job，exact-head evidence 将显示缺失并 NO-GO。Implementation 的 proposed validator 结果只能作为补充证据；Final Review 与 MERGE_AUTHORIZED 还必须由 candidate-external OMP/GitHub 核验按照 base policy重新证明。

bootstrap/rebaseline Scope 的判断只能使用 old/base trusted policy。Proposed policy 永远不能授权产生自己的 transition。

未来每次 policy 变更也必须使用独立、先 Review 后 seed 的 policy-only PR；同一 PR 不得同时修改 policy 及其 consumer、validator 或 CI。

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
/ea-verify      核验指定 PR/candidate/authoritative CI
/ea-bundle      生成并验证 Review Bundle
/ea-next        生成仅推动一个状态转换的下一条 Prompt
/ea-transition  typed old-state -> proposed-state transition
/ea-exec        执行版本化 command profile
```

命令输出不得包含 Secret，并应在非交互/RPC 模式下有确定行为。

`/ea-next` 只生成 Prompt，不自动发送给网页 ChatGPT，不自动推进 state，也不自动 merge。

## 13. 实施分期

### 13.1 Bootstrap policy seed

Docs Gate 合并后，先执行 §9.3 的 policy-only seed PR。Seed 未合并到 main 前，不得启动 Control Plane implementation。

### 13.2 实施观察阶段

Implementation 首先允许 Extension 以 observe 模式运行：

- 每轮注入状态；
- 显示状态 Widget；
- 记录将被阻止的操作；
- 运行测试矩阵；
- 不静默改变工具参数。

### 13.3 强制阶段

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
.github/workflows/ci.yml
docs/architecture/agent-development-workflow.md
.easyaudit/development-state.json
```

具体 allowlist 必须在进入 IMPLEMENTATION 的 state-only 转换中精确列出；此处不是提前授权。`.github/workflows/**` 不得作为宽泛 allowlist，初始实现只允许当前唯一的 `.github/workflows/ci.yml`。

`.easyaudit/workflow-policy.json` 明确不在 Control Plane implementation allowlist 中；它只能由前置 policy-seed PR 按固定 hash 写入。

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
  -> Process OMP Agent Control Plane docs Gate
  -> OMP Control Plane policy seed
  -> OMP Control Plane implementation
  -> M6.1b
  -> resume/rebase M6-Ops implementation
```

当前 Draft PR 不修改或合并停放中的 M6-Ops PR。Control Plane 完成后，M6.1b 仍必须先于 M6-Ops Final Review/merge。该关系必须写入 `.easyaudit/workflow-policy.json` 并由 Git ancestry 验证，不能只依赖本段文字。

每次 phase 转换后，PR body 的 compact status section 应由专用 adapter 同步并重新读取验证。PR body 不是授权源；同步失败时标记 metadata drift，不得把旧 body 当作当前 phase。

## 17. 生命周期

本 Gate Draft 使用 docs-only 生命周期：

```text
GATE_DRAFT
  -> GATE_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED + active=false
```

Gate 合并后，先创建 policy-seed executable PR：

```text
POLICY_SEED IMPLEMENTATION
  -> FINAL_REVIEW (candidate-external bootstrap contract)
  -> MERGE_AUTHORIZED
  -> MERGED + active=false
```

Seed merged main 随后才允许 Control Plane implementation PR：

```text
IMPLEMENTATION (trusted base policy; policy path forbidden)
  -> FINAL_REVIEW
  -> MERGE_AUTHORIZED
  -> MERGED + active=false
```

任何阶段都不得把 Gate Review PASS、proposed policy 或 candidate validator 结果误报为 bootstrap/implementation 完成。
