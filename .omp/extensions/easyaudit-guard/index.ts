import { randomUUID } from 'node:crypto'
import { hostname } from 'node:os'

import type {
  ExtensionAPI,
  ExtensionContext,
  ToolCallEvent,
} from '@oh-my-pi/pi-coding-agent'

interface ControlResult {
  pass: boolean
  reason?: string
  phase?: string
  active?: boolean
  branch?: string
  head?: string
  base?: string
  candidate?: string | null
  working_tree_clean?: boolean
  gate_pass?: boolean
  writer_lease_owned?: boolean
  writer_lease?: { generation_nonce?: string } | null
  runtime_mode?: string
  protection_mode?: string
  policy_trusted?: boolean
  predecessors?: Array<{ slice?: string; pass?: boolean }>
  next_allowed_action?: string
  prompt?: string
  pr?: { headRefOid?: string; state?: string; isDraft?: boolean }
  required_checks?: Array<{ name?: string; pass?: boolean }>
  stdout?: string
  stderr?: string
  returncode?: number
  pr_number?: number
  expected_head?: string
  fixed_candidate?: string
  review?: { reference?: string; candidate?: string; result?: string }
}

const readOnlyProfiles = new Set(['git-status', 'git-diff', 'git-log', 'gate-check'])
const protectedPaths = new Set([
  '.easyaudit/development-state.json',
  '.easyaudit/workflow-policy.json',
])
const trustedControlTools = new Set([
  'ea_status',
  'ea_preflight',
  'ea_verify',
  'ea_next',
  'ea_exec',
  'ea_bootstrap',
  'ea_record_pr',
  'ea_transition',
  'ea_authorized_merge',
  'ea_recover_rebaseline',
  'ea_takeover_lease',
])

function modeName(ctx: ExtensionContext): 'tui' | 'rpc' | 'json' | 'print' {
  return ctx.mode
}

function bounded(text: string, limit = 4000): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}\n[truncated]`
}

function parseJson(output: string): ControlResult {
  try {
    return JSON.parse(output) as ControlResult
  } catch {
    return { pass: false, reason: 'control helper returned invalid JSON' }
  }
}

export default function easyauditGuard(pi: ExtensionAPI) {
  const Type = pi.typebox.Type
  const enforcementMode = process.env.EASYAUDIT_OMP_GUARD_MODE === 'observe'
    ? 'observe'
    : 'enforce'
  let leaseGeneration: string | undefined
  let heartbeat: ReturnType<ExtensionContext['setInterval']> | undefined
  let ownerSessionId: string | undefined
  let ownerSessionFile: string | undefined
  let lastSnapshot: ControlResult | undefined

  async function control(
    args: string[],
    ctx: ExtensionContext,
  ): Promise<ControlResult> {
    ownerSessionId ??= ctx.sessionManager.getSessionId()
    ownerSessionFile ??= ctx.sessionManager.getSessionFile()
    const ownerArgs = [
      '--owner-session', ownerSessionId,
      '--owner-pid', String(process.pid),
      '--owner-host', hostname(),
    ]
    if (ownerSessionFile) ownerArgs.push('--owner-session-file', ownerSessionFile)
    const result = await pi.exec(
      'python3',
      ['scripts/easyaudit_agent.py', ...ownerArgs, ...args],
      { timeout: 30_000 },
    )
    const parsed = parseJson(result.stdout)
    if (result.code !== 0 && parsed.pass !== false) {
      return { pass: false, reason: 'control helper failed' }
    }
    return parsed
  }

  async function refreshStatus(ctx: ExtensionContext): Promise<ControlResult> {
    const snapshot = await control(['status', '--mode', modeName(ctx)], ctx)
    lastSnapshot = snapshot
    const label = snapshot.pass === false
      ? 'BLOCKED'
      : `${snapshot.phase ?? 'UNKNOWN'} | ${snapshot.protection_mode ?? 'read-only-no-go'}`
    ctx.ui.setStatus('easyaudit-guard', `EasyAudit: ${label} | ${enforcementMode}`)
    return snapshot
  }

  async function acquire(ctx: ExtensionContext): Promise<void> {
    const runtimeWriteCapable = ctx.mode === 'tui'
    const launcherToken = process.env.EASYAUDIT_OMP_LAUNCH_TOKEN
    if (!ctx.isProjectTrusted() || !runtimeWriteCapable || !launcherToken) {
      ctx.ui.setStatus('easyaudit-guard', 'EasyAudit: CONTROL PLANE NOT ACTIVATED / read-only-no-go')
      ctx.ui.notify(
        'EASYAUDIT CONTROL PLANE NOT ACTIVE — launch through scripts/easyaudit_agent.py launch.',
        'error',
      )
      return
    }
    const activation = await control(['activation-prove'], ctx)
    if (!activation.pass) {
      ctx.ui.setStatus('easyaudit-guard', 'EasyAudit: activation proof failed / read-only-no-go')
      return
    }
    const result = await control(['lease', 'acquire'], ctx)
    leaseGeneration = result.writer_lease?.generation_nonce
    if (!result.pass || !leaseGeneration) {
      ctx.ui.notify('EasyAudit writer lease unavailable; this Session is read-only.', 'warning')
      await refreshStatus(ctx)
      return
    }
    heartbeat = ctx.setInterval(async () => {
      if (!leaseGeneration) return
      const result = await control(
        ['lease', 'heartbeat', '--generation', leaseGeneration],
        ctx,
      )
      if (!result.pass) {
        leaseGeneration = undefined
        ctx.ui.setStatus('easyaudit-guard', 'EasyAudit: heartbeat failed / read-only-no-go')
        ctx.ui.notify('EasyAudit writer lease heartbeat failed; mutation is disabled.', 'error')
      }
    }, 10_000)
    await refreshStatus(ctx)
  }

  async function release(ctx: ExtensionContext): Promise<void> {
    if (heartbeat) ctx.clearTimer(heartbeat)
    heartbeat = undefined
    if (!leaseGeneration) return
    await control(
      ['lease', 'release', '--generation', leaseGeneration],
      ctx,
    )
    leaseGeneration = undefined
  }

  function targetPath(event: ToolCallEvent): string | undefined {
    const input = event.input as Record<string, unknown>
    const value = input.path
    return typeof value === 'string' ? value : undefined
  }

  function hasTrustedControlProvenance(toolName: string): boolean {
    const tool = pi.getAllTools().find((item) => item.name === toolName)
    if (!tool || tool.sourceInfo.source !== 'extension') return false
    const provenance = `${tool.sourceInfo.path} ${tool.sourceInfo.baseDir ?? ''}`
      .replaceAll('\\\\', '/')
    return provenance.includes('/.omp/extensions/easyaudit-guard')
  }

  async function guard(event: ToolCallEvent, ctx: ExtensionContext) {
    if (
      trustedControlTools.has(event.toolName)
      && !hasTrustedControlProvenance(event.toolName)
    ) {
      return {
        block: true,
        reason: 'EasyAudit control tool provenance is not trusted',
      }
    }
    if (event.toolName === 'ea_exec') {
      const input = event.input as { profile?: unknown }
      if (typeof input.profile === 'string' && readOnlyProfiles.has(input.profile)) {
        return undefined
      }
    }
    const args = [
      'guard',
      '--tool',
      event.toolName,
      '--mode',
      modeName(ctx),
    ]
    const path = targetPath(event)
    if (path) args.push('--path', path)
    const result = await control(args, ctx)
    if (!result.pass) {
      if (enforcementMode === 'observe') {
        ctx.ui.notify(
          `EasyAudit observe-only warning: ${result.reason ?? 'tool would be blocked'}`,
          'warning',
        )
        return undefined
      }
      return {
        block: true,
        reason: result.reason ?? 'EasyAudit control-plane guard blocked this tool',
      }
    }
    return undefined
  }

  async function completeRebaseline(
    pr: number,
    mergeCommit: string,
    ctx: ExtensionContext,
  ): Promise<{ completed: boolean; status: string; mainHead?: string }> {
    const fetched = await pi.exec('git', ['fetch', 'origin'], { timeout: 30_000 })
    if (fetched.code !== 0) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: fetch failed' }
    }
    const remote = await pi.exec('git', ['rev-parse', 'origin/main'], { timeout: 5000 })
    if (remote.code !== 0 || remote.stdout.trim() !== mergeCommit) {
      return {
        completed: false,
        status: `REMOTE_MERGED_REBASELINE_PENDING: merge=${mergeCommit} remote=${remote.stdout.trim() || 'unknown'}`,
      }
    }
    const checkout = await pi.exec('git', ['checkout', 'main'], { timeout: 30_000 })
    if (checkout.code !== 0) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: checkout failed' }
    }
    const reset = await pi.exec('git', ['reset', '--hard', mergeCommit], { timeout: 30_000 })
    if (reset.code !== 0) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: main reset failed' }
    }
    const transitioned = await control(['transition', '--to', 'MERGED'], ctx)
    if (!transitioned.pass) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: state transition failed' }
    }
    const committed = await control(
      ['exec', '--profile', 'git-commit', 'chore: close EasyAudit merge state'],
      ctx,
    )
    if (!committed.pass) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: state commit failed' }
    }
    const pushed = await control(['exec', '--profile', 'git-push-main-rebaseline'], ctx)
    if (!pushed.pass) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: CAS push failed' }
    }
    const mainHead = await pi.exec('git', ['rev-parse', 'HEAD'], { timeout: 5000 })
    const parent = await pi.exec('git', ['rev-parse', 'HEAD^'], { timeout: 5000 })
    const finalRemote = await pi.exec('git', ['rev-parse', 'origin/main'], { timeout: 5000 })
    if (
      mainHead.code !== 0
      || parent.stdout.trim() !== mergeCommit
      || finalRemote.stdout.trim() !== mainHead.stdout.trim()
    ) {
      return { completed: false, status: 'REMOTE_MERGED_REBASELINE_PENDING: final verification failed' }
    }
    return { completed: true, status: 'MERGED_AND_REBASELINED', mainHead: mainHead.stdout.trim() }
  }

  pi.on('session_start', async (_event, ctx) => {
    await acquire(ctx)
  })

  pi.on('session_shutdown', async (_event, ctx) => {
    await release(ctx)
  })

  pi.on('before_agent_start', async (event, ctx) => {
    let snapshot: ControlResult
    try {
      snapshot = await refreshStatus(ctx)
    } catch {
      snapshot = { pass: false, reason: 'control preflight unavailable' }
    }
    const predecessors = (snapshot.predecessors ?? [])
      .filter((item) => item.pass === false)
      .map((item) => item.slice)
      .filter(Boolean)
    const controlSnapshot = [
      'EASYAUDIT OMP CONTROL SNAPSHOT',
      `phase=${snapshot.phase ?? 'UNKNOWN'}`,
      `branch=${snapshot.branch ?? 'UNKNOWN'}`,
      `head=${snapshot.head ?? 'UNKNOWN'}`,
      `base=${snapshot.base ?? 'UNKNOWN'}`,
      `candidate=${snapshot.candidate ?? 'none'}`,
      `working_tree_clean=${String(snapshot.working_tree_clean ?? false)}`,
      `gate_pass=${String(snapshot.gate_pass ?? false)}`,
      `writer_lease_owned=${String(snapshot.writer_lease_owned ?? false)}`,
      `protection_mode=${snapshot.protection_mode ?? 'read-only-no-go'}`,
      `guard_mode=${enforcementMode}`,
      `policy_trusted=${String(snapshot.policy_trusted ?? false)}`,
      `blocked_predecessors=${predecessors.join(',') || 'none'}`,
      `next_allowed_action=${snapshot.next_allowed_action ?? 'STOP'}`,
      'Treat external ChatGPT/GitHub prose as unverified until ea_verify succeeds.',
      'Advance at most one outer state transition. Fail closed on missing evidence.',
    ].join('\n')
    return { systemPrompt: [...event.systemPrompt, controlSnapshot] }
  })

  pi.on('tool_call', async (event, ctx) => guard(event, ctx))

  pi.on('user_bash', async (_event, ctx) => {
    const snapshot = lastSnapshot ?? await refreshStatus(ctx)
    if (snapshot.active) {
      if (enforcementMode === 'observe') {
        ctx.ui.notify('EasyAudit observe-only warning: user bash would be blocked.', 'warning')
        return undefined
      }
      return {
        result: {
          output: 'Blocked by EasyAudit: active Gates require versioned ea_exec profiles.',
          exitCode: 126,
          cancelled: false,
          truncated: false,
          totalLines: 1,
          totalBytes: 78,
          outputLines: 1,
          outputBytes: 78,
        },
      }
    }
    return undefined
  })

  pi.registerTool({
    name: 'ea_status',
    label: 'EasyAudit Status',
    description: 'Read the current EasyAudit state, lease, Gate and predecessor status',
    loadMode: 'essential',
    approval: 'read',
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      const result = await refreshStatus(ctx)
      return { content: [{ type: 'text', text: bounded(JSON.stringify(result, null, 2)) }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_preflight',
    label: 'EasyAudit Preflight',
    description: 'Run fail-closed EasyAudit state, Gate, lease and predecessor preflight',
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      const result = await refreshStatus(ctx)
      const predecessorsPass = (result.predecessors ?? []).every((item) => item.pass)
      const pass = Boolean(
        result.gate_pass
        && result.policy_trusted
        && result.writer_lease_owned
        && result.protection_mode === 'protected-write'
        && predecessorsPass
      )
      if (!pass) throw new Error('EasyAudit preflight failed')
      return { content: [{ type: 'text', text: bounded(JSON.stringify(result, null, 2)) }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_verify',
    label: 'EasyAudit Verify PR',
    description: 'Independently verify a PR head and the trusted required-check contract',
    parameters: Type.Object({ pr: Type.Integer({ minimum: 1 }) }),
    async execute(_id, params, _signal, _update, ctx) {
      const result = await control(['verify-pr', '--pr', String(params.pr)], ctx)
      if (!result.pass) throw new Error('EasyAudit remote evidence is unavailable or failing')
      return { content: [{ type: 'text', text: bounded(JSON.stringify(result, null, 2)) }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_next',
    label: 'EasyAudit Next Prompt',
    description: 'Generate one prompt for only the next legal EasyAudit state action',
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      const result = await control(['next'], ctx)
      return { content: [{ type: 'text', text: result.prompt ?? 'STOP' }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_exec',
    label: 'EasyAudit Approved Command',
    description: 'Execute one versioned EasyAudit command profile without arbitrary shell syntax',
    parameters: Type.Object({
      profile: Type.String(),
      arguments: Type.Optional(Type.Array(Type.String(), { maxItems: 4 })),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      const args = ['exec', '--profile', params.profile, ...(params.arguments ?? [])]
      const result = await control(args, ctx)
      if (!result.pass) throw new Error('Approved command profile failed')
      return {
        content: [{ type: 'text', text: bounded(`${result.stdout ?? ''}${result.stderr ?? ''}`) }],
        details: result,
      }
    },
  })

  pi.registerTool({
    name: 'ea_bootstrap',
    label: 'EasyAudit Slice Bootstrap',
    description: 'Create one typed Gate or implementation state from trusted base policy',
    parameters: Type.Object({
      kind: Type.String(),
      slice: Type.String({ minLength: 1, maxLength: 120 }),
      milestone: Type.String({ minLength: 1, maxLength: 40 }),
      branch: Type.String({ minLength: 1, maxLength: 200 }),
      baseSha: Type.String({ minLength: 40, maxLength: 40 }),
      gateDocs: Type.Array(Type.String(), { minItems: 1, maxItems: 4 }),
      implementationSlice: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
      allowedPaths: Type.Optional(Type.Array(Type.String(), { maxItems: 40 })),
      forbiddenPaths: Type.Optional(Type.Array(Type.String(), { maxItems: 40 })),
      includeRoadmap: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!leaseGeneration || !ctx.hasUI) throw new Error('Writer lease and human UI are required')
      const args = [
        'bootstrap',
        '--kind', params.kind,
        '--slice', params.slice,
        '--milestone', params.milestone,
        '--branch', params.branch,
        '--base-sha', params.baseSha,
      ]
      for (const path of params.gateDocs) args.push('--gate-doc', path)
      if (params.kind === 'gate') {
        if (params.implementationSlice) {
          args.push('--implementation-slice', params.implementationSlice)
        }
        for (const path of params.allowedPaths ?? []) {
          args.push('--implementation-allowed-path', path)
        }
        for (const path of params.forbiddenPaths ?? []) {
          args.push('--implementation-forbidden-path', path)
        }
      }
      if (params.includeRoadmap) args.push('--include-roadmap')
      const plan = await control([...args, '--dry-run'], ctx)
      if (!plan.pass) throw new Error('Slice bootstrap plan is invalid')
      const plannedState = (plan as ControlResult & { state?: unknown }).state
      const nonce = randomUUID()
      const confirmed = await ctx.ui.confirm(
        'Bootstrap one EasyAudit Slice?',
        [
          `kind=${params.kind}`,
          `slice=${params.slice}`,
          `base=${params.baseSha}`,
          `gate=${params.gateDocs.join(',')}`,
          `scope=${bounded(JSON.stringify(plannedState), 1400)}`,
          `nonce=${nonce}`,
        ].join('\n'),
      )
      if (!confirmed) throw new Error('Human bootstrap authorization was not granted')
      const result = await control(args, ctx)
      if (!result.pass) throw new Error('Slice bootstrap failed')
      await refreshStatus(ctx)
      return { content: [{ type: 'text', text: bounded(JSON.stringify(result, null, 2)) }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_record_pr',
    label: 'EasyAudit Record PR',
    description: 'Bind the current Draft/Implementation state to one PR number',
    parameters: Type.Object({ pr: Type.Integer({ minimum: 1 }) }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!leaseGeneration) throw new Error('Writer lease required')
      const result = await control(['record-pr', '--pr', String(params.pr)], ctx)
      if (!result.pass) throw new Error('PR binding failed')
      await refreshStatus(ctx)
      return { content: [{ type: 'text', text: bounded(JSON.stringify(result, null, 2)) }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_takeover_lease',
    label: 'EasyAudit Take Over Stale Lease',
    description: 'Take over one stale/dead writer lease after exact-generation human confirmation',
    parameters: Type.Object({ generation: Type.String({ minLength: 32, maxLength: 64 }) }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!ctx.hasUI) throw new Error('Human UI confirmation is required')
      const snapshot = await refreshStatus(ctx)
      const currentGeneration = snapshot.writer_lease?.generation_nonce
      if (!currentGeneration || currentGeneration !== params.generation) {
        throw new Error('Lease generation evidence is stale')
      }
      const nonce = randomUUID()
      const confirmed = await ctx.ui.confirm(
        'Take over stale EasyAudit writer lease?',
        `generation=${currentGeneration}\naction=stale/dead owner takeover\nnonce=${nonce}`,
      )
      if (!confirmed) throw new Error('Human lease takeover was not authorized')
      const result = await control(
        [
          'lease',
          'takeover',
          '--generation',
          currentGeneration,
          '--remote-owner-confirmed',
        ],
        ctx,
      )
      if (!result.pass || !result.writer_lease?.generation_nonce) {
        throw new Error('Writer lease takeover failed')
      }
      leaseGeneration = result.writer_lease.generation_nonce
      await refreshStatus(ctx)
      return { content: [{ type: 'text', text: 'Writer lease takeover completed.' }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_transition',
    label: 'EasyAudit State Transition',
    description: 'Apply one typed adjacent EasyAudit state transition through the protected adapter',
    parameters: Type.Object({
      target: Type.String(),
      candidate: Type.Optional(Type.String()),
      rollbackReason: Type.Optional(Type.String({ maxLength: 240 })),
      reviewPassRef: Type.Optional(Type.String({ maxLength: 240 })),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!leaseGeneration) throw new Error('Writer lease required')
      if (params.target === 'MERGED') {
        throw new Error('MERGED is internal to authorized merge/rebaseline tools')
      }
      if (params.target === 'MERGE_AUTHORIZED') {
        if (!ctx.hasUI || !params.reviewPassRef) {
          throw new Error('Current human confirmation and Review evidence are required')
        }
        const snapshot = await refreshStatus(ctx)
        if (!snapshot.pr_number || !snapshot.candidate || !snapshot.head) {
          throw new Error('Current PR/candidate/control identity is unavailable')
        }
        const review = await control(
          [
            'review-check',
            '--pr', String(snapshot.pr_number),
            '--candidate', snapshot.candidate,
            '--reference', params.reviewPassRef,
          ],
          ctx,
        )
        const remote = await control(['verify-pr', '--pr', String(snapshot.pr_number)], ctx)
        if (
          !review.pass
          || !remote.pass
          || remote.pr?.headRefOid !== snapshot.head
          || remote.pr?.state !== 'OPEN'
          || remote.pr?.isDraft !== false
        ) {
          throw new Error('Review or exact PR evidence is stale')
        }
        const repository = await pi.exec(
          'gh',
          ['repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'],
          { timeout: 10_000 },
        )
        if (repository.code !== 0) throw new Error('Repository identity is unavailable')
        const nonce = randomUUID()
        const confirmed = await ctx.ui.confirm(
          'Authorize one EasyAudit transition?',
          [
            `repo=${repository.stdout.trim()}`,
            `pr=${snapshot.pr_number}`,
            `reviewed_candidate=${snapshot.candidate}`,
            `control_head=${snapshot.head}`,
            `action=${params.target}`,
            `review=${params.reviewPassRef}`,
            `nonce=${nonce}`,
          ].join('\n'),
        )
        if (!confirmed) throw new Error('Human authorization was not granted')
        const refreshed = await refreshStatus(ctx)
        const reverified = await control(['verify-pr', '--pr', String(snapshot.pr_number)], ctx)
        if (
          refreshed.head !== snapshot.head
          || !reverified.pass
          || reverified.pr?.headRefOid !== snapshot.head
          || reverified.pr?.state !== 'OPEN'
          || reverified.pr?.isDraft !== false
        ) {
          throw new Error('PR evidence drifted after human confirmation')
        }
      }
      const args = ['transition', '--to', params.target]
      if (params.candidate) args.push('--candidate', params.candidate)
      if (params.rollbackReason) args.push('--rollback-reason', params.rollbackReason)
      if (params.reviewPassRef) args.push('--review-pass-ref', params.reviewPassRef)
      const result = await control(args, ctx)
      if (!result.pass) throw new Error('State transition failed')
      await refreshStatus(ctx)
      return { content: [{ type: 'text', text: bounded(JSON.stringify(result, null, 2)) }], details: result }
    },
  })

  pi.registerTool({
    name: 'ea_authorized_merge',
    label: 'EasyAudit Authorized Merge',
    description: 'Reverify, confirm and perform one expected-head PR merge; grant expires in this call',
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      if (!ctx.hasUI || (ctx.mode !== 'tui' && ctx.mode !== 'rpc')) {
        throw new Error('Current human UI confirmation is unavailable')
      }
      const snapshot = await refreshStatus(ctx)
      if (!snapshot.writer_lease_owned || !leaseGeneration) {
        throw new Error('Writer lease is required')
      }
      const before = await control(['merge-eligibility'], ctx)
      if (!before.pass || !before.pr_number || !before.expected_head) {
        throw new Error('PR/candidate/control evidence is not merge-eligible')
      }
      const repository = await pi.exec(
        'gh',
        ['repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'],
        { timeout: 10_000 },
      )
      if (repository.code !== 0) throw new Error('Repository identity is unavailable')
      const nonce = randomUUID()
      const confirmed = await ctx.ui.confirm(
        'Merge and rebaseline one EasyAudit PR?',
        [
          `repo=${repository.stdout.trim()}`,
          `pr=${before.pr_number}`,
          `fixed_candidate=${before.fixed_candidate ?? 'unknown'}`,
          `head=${before.expected_head}`,
          'action=expected-head merge + post-merge state',
          `review=${before.review?.reference ?? 'unknown'}`,
          `nonce=${nonce}`,
        ].join('\n'),
      )
      if (!confirmed) throw new Error('Human merge authorization was not granted')
      const after = await control(['merge-eligibility'], ctx)
      if (
        !after.pass
        || after.pr_number !== before.pr_number
        || after.expected_head !== before.expected_head
      ) {
        throw new Error('PR evidence drifted after confirmation')
      }
      const merged = await pi.exec(
        'gh',
        [
          'api',
          '--method',
          'PUT',
          `repos/${repository.stdout.trim()}/pulls/${before.pr_number}/merge`,
          '-f',
          'merge_method=merge',
          '-f',
          `sha=${before.expected_head}`,
        ],
        { timeout: 30_000 },
      )
      if (merged.code !== 0) throw new Error('Expected-head merge failed')
      const mergePayload = JSON.parse(merged.stdout) as { sha?: string; merged?: boolean }
      if (!mergePayload.merged || !mergePayload.sha) throw new Error('GitHub did not confirm merge')

      const rebaseline = await completeRebaseline(before.pr_number, mergePayload.sha, ctx)
      return {
        content: [{ type: 'text', text: rebaseline.completed
          ? 'Expected-head merge and post-merge rebaseline completed; grant consumed.'
          : `${rebaseline.status}; grant consumed. Use ea_recover_rebaseline after operator confirmation.` }],
        details: {
          pr: before.pr_number,
          expectedHead: before.expected_head,
          mergeCommit: mergePayload.sha,
          rebaseline,
        },
      }
    },
  })

  pi.registerTool({
    name: 'ea_recover_rebaseline',
    label: 'EasyAudit Recover Post-Merge Rebaseline',
    description: 'Recover a remotely merged PR whose state-only rebaseline is still pending',
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      if (!ctx.hasUI || !leaseGeneration) throw new Error('Human UI and writer lease are required')
      const snapshot = await refreshStatus(ctx)
      if (
        !['MERGE_AUTHORIZED', 'MERGED'].includes(snapshot.phase ?? '')
        || !snapshot.pr_number
      ) {
        throw new Error('No remotely merged PR is pending rebaseline')
      }
      const viewed = await pi.exec(
        'gh',
        ['pr', 'view', String(snapshot.pr_number), '--json', 'state,mergeCommit'],
        { timeout: 10_000 },
      )
      if (viewed.code !== 0) throw new Error('Merged PR evidence is unavailable')
      const payload = JSON.parse(viewed.stdout) as {
        state?: string
        mergeCommit?: { oid?: string }
      }
      const mergeCommit = payload.mergeCommit?.oid
      if (payload.state !== 'MERGED' || !mergeCommit) {
        throw new Error('GitHub does not report a merged PR with a merge commit')
      }
      const nonce = randomUUID()
      const confirmed = await ctx.ui.confirm(
        'Recover EasyAudit post-merge state?',
        `pr=${snapshot.pr_number}\nmerge_commit=${mergeCommit}\naction=rebaseline only\nnonce=${nonce}`,
      )
      if (!confirmed) throw new Error('Human recovery authorization was not granted')
      const result = await completeRebaseline(snapshot.pr_number, mergeCommit, ctx)
      if (!result.completed) throw new Error(result.status)
      return {
        content: [{ type: 'text', text: 'Post-merge rebaseline recovery completed.' }],
        details: result,
      }
    },
  })

  pi.registerCommand('ea-status', {
    description: 'Show EasyAudit control-plane status',
    handler: async (_args, ctx) => {
      const result = await refreshStatus(ctx)
      ctx.ui.notify(bounded(JSON.stringify(result, null, 2), 1200), result.pass === false ? 'error' : 'info')
    },
  })

  pi.registerCommand('ea-preflight', {
    description: 'Run EasyAudit preflight',
    handler: async (_args, ctx) => {
      const result = await refreshStatus(ctx)
      ctx.ui.notify(result.gate_pass ? 'EasyAudit preflight passed' : 'EasyAudit preflight blocked', result.gate_pass ? 'info' : 'error')
    },
  })

  pi.registerCommand('ea-next', {
    description: 'Prepare the next legal EasyAudit prompt',
    handler: async (_args, ctx) => {
      const result = await control(['next'], ctx)
      ctx.ui.setEditorText(result.prompt ?? 'STOP')
    },
  })
}
