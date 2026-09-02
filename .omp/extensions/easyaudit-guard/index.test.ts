import assert from 'node:assert/strict'
import test from 'node:test'
import { resolve } from 'node:path'

import {
  discoverExtensionPaths,
  loadExtensions,
  type ExtensionAPI,
} from '@oh-my-pi/pi-coding-agent'
import * as TypeBox from '@oh-my-pi/omptype/typebox'

import easyauditGuard from './index.js'

interface Registered {
  handlers: Map<string, (...args: any[]) => Promise<any>>
  tools: Map<string, any>
  commands: Map<string, any>
}

function harness(options: {
  confirm?: boolean
  phase?: string
  writerLeaseOwned?: boolean
  mode?: 'tui' | 'rpc' | 'json' | 'print'
  remoteAdvanced?: boolean
} = {}): Registered & {
  pi: any
  ctx: any
  confirmations: { count: number }
  merges: { count: number }
  status: Record<string, any>
  leaseAcquires: { count: number }
  stateTransitions: { count: number }
} {
  const handlers = new Map<string, (...args: any[]) => Promise<any>>()
  const tools = new Map<string, any>()
  const commands = new Map<string, any>()
  const status = {
    pass: true,
    active: true,
    phase: options.phase ?? 'IMPLEMENTATION',
    branch: 'codex/example',
    head: 'a'.repeat(40),
    base: 'b'.repeat(40),
    candidate: null,
    working_tree_clean: true,
    gate_pass: true,
    writer_lease_owned: options.writerLeaseOwned ?? false,
    writer_lease: null,
    runtime_mode: 'tui',
    protection_mode: 'read-only-no-go',
    policy_trusted: true,
    predecessors: [],
    next_allowed_action: 'verify only',
  }
  const confirmations = { count: 0 }
  const merges = { count: 0 }
  const leaseAcquires = { count: 0 }
  const stateTransitions = { count: 0 }
  let rebaselinePushed = false
  const pi = {
    typebox: TypeBox,
    on(name: string, handler: (...args: any[]) => Promise<any>) {
      handlers.set(name, handler)
    },
    registerTool(tool: any) {
      tools.set(tool.name, tool)
    },
    registerCommand(name: string, command: any) {
      commands.set(name, command)
    },
    getAllTools() {
      return [...tools.values()].map((tool) => ({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        sourceInfo: {
          source: 'extension',
          path: '/repo/.omp/extensions/easyaudit-guard/index.ts',
          baseDir: '/repo/.omp/extensions/easyaudit-guard',
          scope: 'project',
          origin: 'top-level',
        },
      }))
    },
    async exec(command: string, args: string[]) {
      if (command === 'gh' && args[0] === 'repo') {
        return { code: 0, stdout: 'Truh-hbe/EasyAudit-Next\n', stderr: '' }
      }
      if (command === 'gh' && args[0] === 'api') {
        merges.count += 1
        return {
          code: 0,
          stdout: JSON.stringify({ merged: true, sha: 'm'.repeat(40) }),
          stderr: '',
        }
      }
      if (command === 'git') {
        if (args[0] !== 'rev-parse') return { code: 0, stdout: '', stderr: '' }
        if (args[1] === 'HEAD^') return { code: 0, stdout: `${'m'.repeat(40)}\n`, stderr: '' }
        if (args[1] === 'origin/main') {
          const value = options.remoteAdvanced
            ? 'n'.repeat(40)
            : rebaselinePushed ? 'p'.repeat(40) : 'm'.repeat(40)
          return { code: 0, stdout: `${value}\n`, stderr: '' }
        }
        return { code: 0, stdout: `${'p'.repeat(40)}\n`, stderr: '' }
      }
      assert.equal(command, 'python3')
      if (args.includes('status')) return { code: 0, stdout: JSON.stringify(status), stderr: '' }
      if (args.includes('lease') && args.includes('acquire')) {
        leaseAcquires.count += 1
        return {
          code: 0,
          stdout: JSON.stringify({
            pass: true,
            writer_lease: { generation_nonce: 'generation-a' },
          }),
          stderr: '',
        }
      }
      if (args.includes('lease') && args.includes('release')) {
        return { code: 0, stdout: JSON.stringify({ pass: true }), stderr: '' }
      }
      if (args.includes('merge-eligibility')) {
        return {
          code: 0,
          stdout: JSON.stringify({
            pass: true,
            pr_number: 45,
            expected_head: 'a'.repeat(40),
            fixed_candidate: 'f'.repeat(40),
            review: { reference: 'comment:1', candidate: 'f'.repeat(40), result: 'PASS' },
          }),
          stderr: '',
        }
      }
      if (args.includes('transition') && args.includes('MERGED')) {
        stateTransitions.count += 1
        return { code: 0, stdout: JSON.stringify({ pass: true }), stderr: '' }
      }
      if (args.includes('git-push-main-rebaseline')) {
        rebaselinePushed = true
        return { code: 0, stdout: JSON.stringify({ pass: true }), stderr: '' }
      }
      if (args.includes('verify-pr')) {
        return {
          code: 0,
          stdout: JSON.stringify({
            pass: true,
            pr: { headRefOid: 'a'.repeat(40), state: 'OPEN', isDraft: false },
            required_checks: [
              { name: 'check', pass: true },
              { name: 'frontend', pass: true },
              { name: 'browser-acceptance', pass: true },
            ],
          }),
          stderr: '',
        }
      }
      if (args.includes('guard')) {
        return {
          code: 2,
          stdout: JSON.stringify({ pass: false, reason: 'no writer lease' }),
          stderr: '',
        }
      }
      return { code: 0, stdout: JSON.stringify({ pass: true }), stderr: '' }
    },
  }
  const ctx = {
    mode: options.mode ?? 'tui',
    sessionManager: {
      getSessionId: () => 'omp-session-a',
      getSessionFile: () => '/tmp/omp-session-a.jsonl',
    },
    setInterval: () => ({ id: 'timer' }),
    clearTimer() {},
    hasUI: true,
    signal: undefined,
    isProjectTrusted: () => true,
    ui: {
      setStatus() {},
      notify() {},
      setEditorText() {},
      async confirm() {
        confirmations.count += 1
        return options.confirm ?? false
      },
    },
  }
  easyauditGuard(pi as unknown as ExtensionAPI)
  return {
    handlers,
    tools,
    commands,
    pi,
    ctx,
    confirmations,
    merges,
    status,
    leaseAcquires,
    stateTransitions,
  }
}

test('OMP native discovery and loader find the project guard', async () => {
  const root = resolve(import.meta.dirname, '../../..')
  const guard = resolve(import.meta.dirname, 'index.ts')
  const discovered = await discoverExtensionPaths([], root, [], {
    ambient: true,
    includeAmbientHooks: false,
  })
  assert.ok(discovered.includes(guard), 'native OMP discovery did not find the guard')
  const loaded = await loadExtensions([guard], root)
  assert.deepEqual(loaded.errors, [])
  assert.equal(loaded.extensions.length, 1)
  const registered = loaded.extensions[0]?.tools.get('ea_status')
  assert.ok(registered)
  assert.match(registered.extensionPath.replaceAll('\\\\', '/'), /easyaudit-guard\/index\.ts$/)
})

test('injects a fresh control snapshot before every agent turn', async () => {
  const { handlers, ctx, status } = harness()
  const handler = handlers.get('before_agent_start')
  assert.ok(handler)
  const first = await handler({ systemPrompt: ['base'] }, ctx)
  const firstPrompt = first.systemPrompt.join('\n')
  assert.match(firstPrompt, /EASYAUDIT OMP CONTROL SNAPSHOT/)
  assert.match(firstPrompt, /phase=IMPLEMENTATION/)
  assert.match(firstPrompt, /protection_mode=read-only-no-go/)
  status.phase = 'FINAL_REVIEW'
  status.head = 'c'.repeat(40)
  const second = await handler({ systemPrompt: ['base'] }, ctx)
  const secondPrompt = second.systemPrompt.join('\n')
  assert.match(secondPrompt, /phase=FINAL_REVIEW/)
  assert.match(secondPrompt, new RegExp(`head=${'c'.repeat(40)}`))
})

test('blocks model-facing mutation when the helper refuses it', async () => {
  const { handlers, ctx } = harness()
  const handler = handlers.get('tool_call')
  assert.ok(handler)
  const result = await handler({ toolName: 'bash', input: { command: 'true' } }, ctx)
  assert.deepEqual(result, { block: true, reason: 'no writer lease' })
})

test('rejects an ea-prefixed tool without EasyAudit extension provenance', async () => {
  const { handlers, ctx, pi } = harness()
  pi.getAllTools = () => [{
    name: 'ea_exec',
    description: 'unsafe',
    parameters: {},
    sourceInfo: {
      source: 'extension',
      path: '/tmp/third-party/index.ts',
      scope: 'project',
      origin: 'top-level',
    },
  }]
  const handler = handlers.get('tool_call')
  assert.ok(handler)
  const result = await handler({ toolName: 'ea_exec', input: {} }, ctx)
  assert.deepEqual(result, {
    block: true,
    reason: 'EasyAudit control tool provenance is not trusted',
  })
})

test('observe mode warns without claiming hard enforcement', async () => {
  process.env.EASYAUDIT_OMP_GUARD_MODE = 'observe'
  try {
    const { handlers, ctx } = harness()
    const handler = handlers.get('tool_call')
    assert.ok(handler)
    const result = await handler({ toolName: 'bash', input: { command: 'true' } }, ctx)
    assert.equal(result, undefined)
  } finally {
    delete process.env.EASYAUDIT_OMP_GUARD_MODE
  }
})

test('direct OMP session without launcher activation cannot acquire writer lease', async () => {
  delete process.env.EASYAUDIT_OMP_LAUNCH_TOKEN
  const { handlers, ctx, leaseAcquires } = harness({ mode: 'tui' })
  const sessionStart = handlers.get('session_start')
  assert.ok(sessionStart)
  await sessionStart({}, ctx)
  assert.equal(leaseAcquires.count, 0)
})

test('unverified RPC runtime remains read-only and does not hold the writer lease', async () => {
  process.env.EASYAUDIT_OMP_LAUNCH_TOKEN = 'a'.repeat(64)
  const { handlers, ctx, leaseAcquires } = harness({ mode: 'rpc' })
  const sessionStart = handlers.get('session_start')
  assert.ok(sessionStart)
  await sessionStart({}, ctx)
  assert.equal(leaseAcquires.count, 0)
  delete process.env.EASYAUDIT_OMP_LAUNCH_TOKEN
})

test('blocks the independent user-bash surface during an active Gate', async () => {
  const { handlers, ctx } = harness()
  const handler = handlers.get('user_bash')
  assert.ok(handler)
  const result = await handler({ command: 'git status' }, ctx)
  assert.equal(result.result.exitCode, 126)
  assert.match(result.result.output, /ea_exec profiles/)
})

test('registers the required control tools and commands', () => {
  const { tools, commands } = harness()
  for (const name of [
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
  ]) {
    assert.ok(tools.has(name), `missing tool ${name}`)
  }
  for (const name of ['ea-status', 'ea-preflight', 'ea-next']) {
    assert.ok(commands.has(name), `missing command ${name}`)
  }
})

test('cancelled human merge challenge performs no action', async () => {
  process.env.EASYAUDIT_OMP_LAUNCH_TOKEN = 'a'.repeat(64)
  const { tools, ctx, handlers, confirmations, merges } = harness({
    confirm: false,
    phase: 'MERGE_AUTHORIZED',
    writerLeaseOwned: true,
  })
  const sessionStart = handlers.get('session_start')
  const sessionShutdown = handlers.get('session_shutdown')
  assert.ok(sessionStart)
  assert.ok(sessionShutdown)
  await sessionStart({}, ctx)
  const tool = tools.get('ea_authorized_merge')
  await assert.rejects(
    tool.execute('call', {}, undefined, undefined, ctx),
    /authorization was not granted/,
  )
  assert.equal(confirmations.count, 1)
  assert.equal(merges.count, 0)
  await sessionShutdown({}, ctx)
  delete process.env.EASYAUDIT_OMP_LAUNCH_TOKEN
})

test('remote main advance is detected before any state transition', async () => {
  process.env.EASYAUDIT_OMP_LAUNCH_TOKEN = 'a'.repeat(64)
  const { tools, ctx, handlers, stateTransitions } = harness({
    confirm: true,
    phase: 'MERGE_AUTHORIZED',
    writerLeaseOwned: true,
    remoteAdvanced: true,
  })
  const sessionStart = handlers.get('session_start')
  const sessionShutdown = handlers.get('session_shutdown')
  assert.ok(sessionStart)
  assert.ok(sessionShutdown)
  await sessionStart({}, ctx)
  const tool = tools.get('ea_authorized_merge')
  const result = await tool.execute('call', {}, undefined, undefined, ctx)
  assert.match(result.content[0].text, /REMOTE_MERGED_REBASELINE_PENDING/)
  assert.equal(stateTransitions.count, 0)
  await sessionShutdown({}, ctx)
  delete process.env.EASYAUDIT_OMP_LAUNCH_TOKEN
})

test('human merge confirmation is consumed inside each exact action', async () => {
  process.env.EASYAUDIT_OMP_LAUNCH_TOKEN = 'a'.repeat(64)
  const { tools, ctx, handlers, confirmations, merges } = harness({
    confirm: true,
    phase: 'MERGE_AUTHORIZED',
    writerLeaseOwned: true,
  })
  const sessionStart = handlers.get('session_start')
  const sessionShutdown = handlers.get('session_shutdown')
  assert.ok(sessionStart)
  assert.ok(sessionShutdown)
  await sessionStart({}, ctx)
  const tool = tools.get('ea_authorized_merge')
  for (let index = 0; index < 2; index += 1) {
    await tool.execute(`call-${index}`, {}, undefined, undefined, ctx)
  }
  assert.equal(confirmations.count, 2)
  assert.equal(merges.count, 2)
  await sessionShutdown({}, ctx)
  delete process.env.EASYAUDIT_OMP_LAUNCH_TOKEN
})
