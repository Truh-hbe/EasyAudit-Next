import { randomUUID } from 'node:crypto'

import type {
  ExtensionAPI,
  ExtensionContext,
  ToolCallEvent,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

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
}

const readOnlyProfiles = new Set(['git-status', 'git-diff', 'git-log', 'gate-check'])
const protectedPaths = new Set([
  '.easyaudit/development-state.json',
  '.easyaudit/workflow-policy.json',
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
  const enforcementMode = process.env.EASYAUDIT_OMP_GUARD_MODE === 'observe'
    ? 'observe'
    : 'enforce'
  let leaseGeneration: string | undefined
  let heartbeat: ReturnType<typeof setInterval> | undefined
  let lastSnapshot: ControlResult | undefined

  async function control(
    args: string[],
    ctx: ExtensionContext,
  ): Promise<ControlResult> {
    const result = await pi.exec('python3', ['scripts/easyaudit_agent.py', ...args], {
      timeout: 30_000,
      signal: ctx.signal,
    })
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
      || (ctx.mode === 'rpc' && process.env.EASYAUDIT_OMP_RPC_BASH_GUARDED === '1')
    if (!ctx.isProjectTrusted() || !runtimeWriteCapable) {
      ctx.ui.setStatus('easyaudit-guard', 'EasyAudit: read-only-no-go')
      return
    }
    const result = await control(['lease', 'acquire'], ctx)
    leaseGeneration = result.writer_lease?.generation_nonce
    if (!result.pass || !leaseGeneration) {
      ctx.ui.notify('EasyAudit writer lease unavailable; this Session is read-only.', 'warning')
      await refreshStatus(ctx)
      return
    }
    heartbeat = setInterval(() => {
      if (!leaseGeneration) return
      void pi.exec(
        'python3',
        [
          'scripts/easyaudit_agent.py',
          'lease',
          'heartbeat',
          '--generation',
          leaseGeneration,
        ],
        { timeout: 5000 },
      )
    }, 10_000)
    await refreshStatus(ctx)
  }

  async function release(): Promise<void> {
    if (heartbeat) clearInterval(heartbeat)
    heartbeat = undefined
    if (!leaseGeneration) return
    await pi.exec(
      'python3',
      [
        'scripts/easyaudit_agent.py',
        'lease',
        'release',
        '--generation',
        leaseGeneration,
      ],
      { timeout: 5000 },
    )
    leaseGeneration = undefined
  }

  function targetPath(event: ToolCallEvent): string | undefined {
    const input = event.input as Record<string, unknown>
    const value = input.path
    return typeof value === 'string' ? value : undefined
  }

  async function guard(event: ToolCallEvent, ctx: ExtensionContext) {
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

  pi.on('session_start', async (_event, ctx) => {
    await acquire(ctx)
  })

  pi.on('session_shutdown', async () => {
    await release()
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
    return { systemPrompt: `${event.systemPrompt}\n\n${controlSnapshot}` }
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
        },
      }
    }
    return undefined
  })

  pi.registerTool({
    name: 'ea_status',
    label: 'EasyAudit Status',
    description: 'Read the current EasyAudit state, lease, Gate and predecessor status',
    promptSnippet: 'Inspect EasyAudit control-plane status before planning or mutation',
    promptGuidelines: [
      'Use ea_status before planning, modifying, reviewing, merging or deploying EasyAudit work.',
    ],
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
      allowedPaths: Type.Optional(Type.Array(Type.String(), { maxItems: 40 })),
      forbiddenPaths: Type.Optional(Type.Array(Type.String(), { maxItems: 40 })),
      includeRoadmap: Type.Optional(Type.Boolean()),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!leaseGeneration || !ctx.hasUI) throw new Error('Writer lease and human UI are required')
      const nonce = randomUUID()
      const confirmed = await ctx.ui.confirm(
        'Bootstrap one EasyAudit Slice?',
        `kind=${params.kind}\nslice=${params.slice}\nbase=${params.baseSha}\nnonce=${nonce}`,
      )
      if (!confirmed) throw new Error('Human bootstrap authorization was not granted')
      const args = [
        'bootstrap',
        '--kind', params.kind,
        '--slice', params.slice,
        '--milestone', params.milestone,
        '--branch', params.branch,
        '--base-sha', params.baseSha,
      ]
      for (const path of params.gateDocs) args.push('--gate-doc', path)
      for (const path of params.allowedPaths ?? []) args.push('--allowed-path', path)
      for (const path of params.forbiddenPaths ?? []) args.push('--forbidden-path', path)
      if (params.includeRoadmap) args.push('--include-roadmap')
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
      if (params.target === 'MERGE_AUTHORIZED') {
        if (!ctx.hasUI) throw new Error('Current human confirmation is unavailable')
        const nonce = randomUUID()
        const confirmed = await ctx.ui.confirm(
          'Authorize one EasyAudit transition?',
          `target=${params.target}\nhead=${lastSnapshot?.head ?? 'unknown'}\nnonce=${nonce}`,
        )
        if (!confirmed) throw new Error('Human authorization was not granted')
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
    parameters: Type.Object({
      pr: Type.Integer({ minimum: 1 }),
      expectedHead: Type.String({ minLength: 40, maxLength: 40 }),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!ctx.hasUI || (ctx.mode !== 'tui' && ctx.mode !== 'rpc')) {
        throw new Error('Current human UI confirmation is unavailable')
      }
      const snapshot = await refreshStatus(ctx)
      if (
        snapshot.phase !== 'MERGE_AUTHORIZED'
        || !snapshot.writer_lease_owned
        || !leaseGeneration
      ) {
        throw new Error('MERGE_AUTHORIZED phase and writer lease are required')
      }
      const before = await control(['verify-pr', '--pr', String(params.pr)], ctx)
      if (
        !before.pass
        || before.pr?.headRefOid !== params.expectedHead
        || before.pr?.state !== 'OPEN'
        || before.pr?.isDraft !== false
      ) {
        throw new Error('PR evidence or expected head is stale')
      }
      const nonce = randomUUID()
      const confirmed = await ctx.ui.confirm(
        'Merge and rebaseline one EasyAudit PR?',
        `pr=${params.pr}\nhead=${params.expectedHead}\naction=expected-head merge + post-merge state\nnonce=${nonce}`,
      )
      if (!confirmed) throw new Error('Human merge authorization was not granted')
      const after = await control(['verify-pr', '--pr', String(params.pr)], ctx)
      if (!after.pass || after.pr?.headRefOid !== params.expectedHead) {
        throw new Error('PR evidence drifted after confirmation')
      }
      const repository = await pi.exec('gh', ['repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], { timeout: 10_000 })
      if (repository.code !== 0) throw new Error('Repository identity is unavailable')
      const merged = await pi.exec(
        'gh',
        [
          'api',
          '--method',
          'PUT',
          `repos/${repository.stdout.trim()}/pulls/${params.pr}/merge`,
          '-f',
          'merge_method=merge',
          '-f',
          `sha=${params.expectedHead}`,
        ],
        { timeout: 30_000 },
      )
      if (merged.code !== 0) throw new Error('Expected-head merge failed')
      const mergePayload = JSON.parse(merged.stdout) as { sha?: string; merged?: boolean }
      if (!mergePayload.merged || !mergePayload.sha) throw new Error('GitHub did not confirm merge')

      for (const [command, args] of [
        ['git', ['fetch', 'origin']],
        ['git', ['checkout', 'main']],
        ['git', ['merge', '--ff-only', 'origin/main']],
      ] as const) {
        const result = await pi.exec(command, [...args], { timeout: 30_000 })
        if (result.code !== 0) throw new Error('Post-merge main synchronization failed')
      }
      const transitioned = await control(['transition', '--to', 'MERGED'], ctx)
      if (!transitioned.pass) throw new Error('Post-merge state transition failed')
      const committed = await control(
        [
          'exec',
          '--profile',
          'git-commit',
          'chore: close EasyAudit merge state',
        ],
        ctx,
      )
      if (!committed.pass) throw new Error('Post-merge state commit failed')
      const pushed = await control(
        ['exec', '--profile', 'git-push-main-rebaseline'],
        ctx,
      )
      if (!pushed.pass) throw new Error('Post-merge main push failed')

      const mainHead = await pi.exec('git', ['rev-parse', 'HEAD'], { timeout: 5000 })
      const parent = await pi.exec('git', ['rev-parse', 'HEAD^'], { timeout: 5000 })
      const remote = await pi.exec('git', ['rev-parse', 'origin/main'], { timeout: 5000 })
      if (
        mainHead.code !== 0
        || parent.stdout.trim() !== mergePayload.sha
        || remote.stdout.trim() !== mainHead.stdout.trim()
      ) {
        throw new Error('Post-merge ancestry or remote verification failed')
      }
      return {
        content: [{ type: 'text', text: 'Expected-head merge and post-merge rebaseline completed; grant consumed.' }],
        details: {
          pr: params.pr,
          expectedHead: params.expectedHead,
          mergeCommit: mergePayload.sha,
          mainHead: mainHead.stdout.trim(),
        },
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
