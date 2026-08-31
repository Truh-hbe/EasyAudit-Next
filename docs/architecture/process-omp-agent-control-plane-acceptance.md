# OMP Agent Control Plane Hardening Acceptance

## Acceptance principle

该切片只有在以下命题均得到机器证据时才通过：

> 即使 OMP Agent 遗忘历史对话、经历上下文压缩、收到错误外部声明、遭遇 GitHub Connector 故障，或与另一 Session 竞争工作区，它也不能在没有合法 state、scope、lease、证据与人类授权的情况下继续写入、合并或部署。

Prompt、Skill 文本存在本身不是充分证据。必须证明 Extension、脚本、测试和 CI 的实际行为。

## 1. Gate Draft 验收

当前 Gate Draft 必须严格 docs-only：

- 只修改 `.easyaudit/development-state.json`、Roadmap 和两份 Control Plane Gate 文档；
- `candidate_kind=docs-only`；
- `phase=GATE_DRAFT`；
- `fixed_head=null`；
- `docs_review_head=null`；
- 不修改 `AGENTS.md`、`.omp/**`、脚本、测试、CI 或产品代码；
- 不推进 M6.1b、M6-Ops 或任何产品 Slice；
- 不授权 merge、deployment、secret access、restore rehearsal 或 traffic。

## 2. 术语验收

项目面向用户与项目流程的正式名称必须是：

```text
OMP Agent
```

新建的 Skill、Prompt、Extension、命令、文档和输出不得称该项目角色为 Pi Agent。实现可使用底层兼容 API，但目录解析必须尊重运行时配置，当前项目资源位于 `.omp`。

## 3. 每轮动态快照

对连续两个用户请求，Extension 必须在每轮 `before_agent_start` 或等价生命周期中重新读取状态并注入控制快照。

测试必须证明第一次与第二次请求之间修改：

```text
phase
HEAD
working-tree state
allowed next action
```

后，第二轮收到新值而不是历史缓存。

快照至少包含：

```text
phase
branch
HEAD
base
candidate
working tree clean/dirty
writer lease owner/state
Gate check pass/fail
allowed next action
remote evidence freshness
```

不得包含 Secret、Prompt 内容或业务 payload。

## 4. Compaction 与 Session 生命周期

通过 Extension 生命周期测试或可重复 harness 证明，在以下事件后下一轮仍重新注入控制快照：

```text
startup
reload
new
resume
fork/clone
compaction 后下一轮
```

不得依赖 compaction summary 保存 phase、SHA 或授权。

## 5. 项目 Skill

`.omp/skills/easyaudit-control-plane/SKILL.md` 必须：

- 具有合法 frontmatter；
- description 可匹配 EasyAudit 中的 plan/mutate/review/merge/deploy/verify 请求；
- 正文包含 startup、phase、scope、candidate/control、evidence、connector fallback、lease、compaction 和 stop conditions；
- 所有相对引用可解析；
- 可通过 `/skill:easyaudit-control-plane` 显式加载；
- 不包含真实凭据或环境 Secret。

Skill 自动触发测试只能作为补充；强制性必须来自 Extension 和 Gate。

## 6. Prompt Templates

至少验证以下模板可被 OMP 发现并正确展开：

```text
ea-status
ea-gate-draft
ea-gate-review
ea-address-findings
ea-final-review
ea-merge
ea-next
```

每个会改变状态的模板必须：

- 只推动一个状态转换；
- 包含 exact refs 参数；
- 包含 allowed/forbidden actions；
- 包含返回证据格式；
- 包含停止条件；
- 不内置自动 merge/deploy 授权。

负面测试必须拒绝一个把 implementation、review 和 merge 组合成单步自动执行的模板。

## 7. Per-turn 分类协议

`AGENTS.md` 必须定义：

```text
READ_ONLY / PLAN / MUTATE / REVIEW / MERGE / DEPLOY
```

测试或静态校验必须证明每类均绑定明确前置条件。至少验证：

- PLAN 要求 Roadmap predecessor 检查；
- MUTATE 要求 preflight 和 writer lease；
- REVIEW 要求固定 candidate；
- MERGE 要求 MERGE_AUTHORIZED、exact-head CI、人类授权与 expected-head；
- DEPLOY 要求环境 Gate 和操作员授权。

## 8. Writer lease 原子性

使用两个独立进程或等价真实并发 harness：

1. Session A 获取 writer lease；
2. Session B 同时申请 writer；
3. B 必须失败或只读降级；
4. B 的 edit/write/mutating bash 被阻止；
5. A 正常释放后 B 才能获取。

不能用单进程顺序 mock 替代并发证明。

## 9. Lease owner 与 stale recovery

测试矩阵必须覆盖：

- 活跃同主机 PID + 新鲜 heartbeat：禁止抢占；
- 活跃 PID + 旧时间：仍禁止静默抢占；
- 不存在 PID + heartbeat 未超时：默认禁止自动抢占；
- 不存在 PID + 超时：要求显式 takeover；
- owner 不可验证：fail-closed 或人工确认；
- Session shutdown 只释放自己拥有的 lease；
- 非 owner 无法删除或刷新 lease；
- 崩溃遗留 lease 可在规则满足后恢复。

租约文件必须位于 Git 忽略目录。获取/刷新租约不得使 working tree 变脏。

## 10. 并发工作区事故回归

建立本次真实事故的回归测试：

```text
Session A 正在诊断并修改测试文件
Session B 尝试提交同一工作区并更新 development-state
```

B 必须在任何 commit/state edit 前被阻止。测试输出应明确显示当前 owner session，不泄漏对话内容。

## 11. Scope 写入阻断

在 active Gate fixture 中分别调用 edit/write：

- allowed path：可进入后续检查；
- unmatched path：阻止；
- forbidden path：阻止；
- repository root 外路径：阻止；
- symlink 指向 forbidden/root 外路径：阻止；
- state JSON 无法解析：阻止；
- Gate check 失败：阻止；
- 无 writer lease：阻止。

路径判断必须基于规范化 real path，并与 Git root 绑定。

## 12. Phase 阻断

测试以下矩阵：

| Phase | 操作 | 预期 |
|---|---|---|
| GATE_DRAFT | docs allowed path | 允许 |
| GATE_DRAFT | executable path | 阻止 |
| GATE_REVIEW | Gate 文档再修改 | 除明确修订流程外阻止/要求退回 Draft |
| IMPLEMENTATION | allowed executable | 允许 |
| FINAL_REVIEW | 任意非 finalization 修改 | 阻止 |
| FINAL_REVIEW | dirty working tree | Final Review 失败 |
| MERGE_AUTHORIZED | non-state change | 阻止 |
| MERGED active=false | mutation | 仅显式新任务可启动，不继承旧授权 |

## 13. Final Review 脏工作区回归

复现：

```text
phase=FINAL_REVIEW
fixed_head valid
working tree has modified executable test
```

以下都必须失败：

```text
/ea-preflight for review
/ea-bundle final-review mode
merge eligibility
CI Gate check path used for Final Review
```

不能再次出现普通 `check` 显示 pass 而 Agent 宣称 Final Review 就绪的情况。

## 14. Failed CI 状态回归

给定：

```text
fixed candidate exists
latest exact-head required CI has one failed job
```

Control Plane 必须：

- 报告 NO-GO；
- 禁止 `MERGE_AUTHORIZED`；
- 禁止 merge；
- 生成回退至 IMPLEMENTATION/修复流程的 Prompt；
- 不把其他 green job 抵消失败 job。

## 15. Candidate/control 完整性

测试 executable 与 docs-only 两类：

- Candidate 后只有 state-only control commit：通过；
- Candidate 后 source/test/CI commit：失败；
- fixed head 不存在/非 ancestor：失败；
- docs review head 不存在/非 ancestor：失败；
- synthetic merge ref 不得冒充 PR head；
- Review Bundle 与旧 state/head 对应：失败；
- working tree diff 必须独立记录。

## 16. Acceptance 弱化检测

使用本次测试修改作为 fixture：

```text
expect(attempts).toBe(2)
  -> expect(attempts).toBeGreaterThanOrEqual(2)
```

Control Plane 不需要通用理解所有测试语义，但必须至少做到：

- Candidate 固定后任何 test 变更被阻止；
- Review Prompt 明确要求检查 assertion weakening；
- diff/evidence 中 test changes 不得被隐藏；
- Agent 不得仅因新测试 green 就自动消除 Review finding。

## 17. Roadmap predecessor

构造：

```text
A -> B -> C
A complete
B incomplete
请求启动 C implementation
```

`/ea-next` 与每轮 PLAN/MUTATE preflight 必须报告 B 未完成，并拒绝生成可执行 C 的指令。

以真实路线验证：M6.1b 未完成时不得批准 M6-Ops Final Review/merge。

## 18. 外部声明核验

输入伪造的：

```text
PR number
commit SHA
CI green 声明
merged 声明
main HEAD
```

`/ea-verify` 必须通过 Git/GitHub 重新读取并报告差异，不得回显为已验证事实。

离线或 GitHub 不可用时结果必须是：

```text
remote evidence unavailable/stale
```

而不是 pass。

## 19. Connector 降级

模拟网页 GitHub Connector 的 Draft → Ready mutation 失败：

- Control Plane 可建议或执行 `gh pr ready`；
- 操作后必须 `gh pr view` 复核；
- phase 与授权不因 Connector 失败自动改变；
- 非 MERGE_AUTHORIZED 时 `gh pr merge` 被阻止；
- required CI 未绿时 merge 被阻止；
- 缺少人类当前授权时 merge 被阻止。

## 20. Expected-head merge

在临时 GitHub adapter/harness 中验证：

- expected head 与 PR head 一致：进入 merge adapter；
- expected head 已漂移：阻止；
- synthetic merge SHA 被当作 expected head：阻止；
- merge 后必须核验 PR merged、main head、merge parent/tree 和 post-merge state；
- 任一核验失败不得宣称闭环完成。

真实 GitHub destructive merge 不要求在单元测试中执行。

## 21. Bash 防护

至少阻止或要求授权：

```text
git reset --hard
git clean -fd
git push --force
gh pr merge
docker compose against non-test environment
deploy/restore/secret commands
```

测试必须证明普通只读命令不被误阻止。

文档和实现不得宣称 shell 字符串规则可以解析任意脚本语义；最终 diff/CI 仍是权威兜底。

## 22. OMP 命令

### `/ea-status`

必须输出有界、无 Secret 的状态摘要，不修改仓库。

### `/ea-preflight`

必须运行 state/branch/base/working-tree/lease/Gate 检查，并以非零或明确 blocked 结果表示失败。

### `/ea-verify`

必须支持 PR/candidate 核验，标记 remote evidence 时间。

### `/ea-bundle`

必须生成当前 Bundle，并在 review/final 模式要求 clean/current evidence。

### `/ea-next`

必须只生成下一合法状态动作的 Prompt，不修改 state、不发送 Prompt、不 merge。

## 23. 非交互模式

Extension 在 TUI、RPC、JSON/print 或无 UI 场景中必须有确定的 fail-closed 行为：

- 需要确认但无 UI 时，不得默认批准；
- mutation/merge/deploy 返回 blocked；
- read-only status 可输出结构化结果；
- 不启动无法在 session shutdown 清理的后台资源。

## 24. Secret negative

将 unmistakable sentinel 放入：

```text
环境变量名/值
Git remote URL fixture
Prompt text
Connector error
lease metadata surrounding input
```

Extension 日志、Widget、命令输出、测试快照和 Review Bundle 不得出现 sentinel 值。错误只输出 bounded class/reason。

## 25. Resource discovery 与 trust

在受信项目中验证：

- `.omp` Project Skill、Prompt 和 Extension 被发现；
- `/reload` 后新版本生效；
- startup 显示 guard active；
- guard 未加载/项目未信任时给出明显 NO-GO，而不是静默假装受保护；
- 文档要求对精确仓库路径执行项目 trust，不建议全局 `always trust`。

## 26. Extension 故障

人为让 state parser、lease reader 或 Gate subprocess 抛错：

- read-only 可带 degraded warning；
- edit/write/mutating bash 被阻止；
- merge/deploy 被阻止；
- 错误不泄漏 raw state/command Secret；
- Extension 故障不会被解释为授权。

## 27. CI 与静态检查

Canonical CI 至少验证：

- Skill frontmatter 和引用；
- Prompt 模板集合与单状态转换规则；
- Extension typecheck/lint/tests；
- lease 并发测试；
- scope/phase/tool-call guard matrix；
- dirty Final Review 回归；
- candidate/control matrix；
- Gate tooling tests；
- architecture check；
- 未修改产品路径。

## 28. Observe → Enforce 切换

Implementation 可以先运行 observe 模式，但 Final candidate 必须证明：

```text
default mode = enforce
```

测试中 observe 模式只告警，enforce 模式实际阻止。生产使用说明不得让用户误以为 observe 已提供硬保护。

## 29. 性能与稳定性

每轮本地轻量 preflight 不应执行完整测试套件或无条件网络 fetch。

验收预算建议：

```text
local state snapshot p95 < 500 ms
no-network preflight p95 < 2 s
```

涉及 GitHub 的验证可有独立超时，并明确标记 freshness。超时不得阻塞 TUI 无限等待。

## 30. Go / No-Go

### Go

只有以下全部满足才可通过：

```text
P0 = 0
P1 = 0
P2 = 0
```

并且：

- 每轮动态控制快照有效；
- 单 writer lease 并发测试通过；
- scope/phase 写阻断通过；
- Final Review dirty-worktree 回归通过；
- failed-CI 和 predecessor 回归通过；
- Candidate/control/Bundle 检查通过；
- Connector 降级不扩大权限；
- Prompt 只推动一个状态转换；
- Skill/Prompt/Extension 可被受信项目发现；
- enforce 为默认模式；
- exact-head CI 全绿；
- 人类明确授权合并。

### No-Go

以下任一情况为 No-Go：

- 仅依赖 AGENTS/Skill/Prompt，没有工具层阻断；
- 仅依赖 Extension，没有 CI/Gate 兜底；
- 两个 OMP Session 可同时写同一工作区；
- Final Review 允许脏 executable 工作区；
- failed CI 可进入 MERGE_AUTHORIZED；
- Roadmap predecessor 可被跳过；
- Connector 故障会自动扩大权限；
- 无 UI 确认被默认视为批准；
- Candidate 固定后测试/代码可继续变化；
- Extension 未加载时没有明显告警；
- lease、日志或输出泄漏 Secret；
- 通过修改产品代码来实现 Agent 控制面。

## 31. Gate Review 输出要求

独立 Gate Review 必须明确回答：

1. writer lease 是否能可靠处理多 Session、崩溃与 takeover；
2. Extension 阻断与 Gate/CI 权威是否正确分层；
3. bash 防护是否存在被误称为完整沙箱的过度声明；
4. Final Review dirty-worktree 与 failed-CI 缺口是否被真正关闭；
5. `/ea-next` 是否会跨 Roadmap predecessor；
6. Connector 降级是否保持人类授权；
7. implementation allowlist 是否足够窄；
8. 是否存在任何产品、部署或 Secret 权限扩张。
