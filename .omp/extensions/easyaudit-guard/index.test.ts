import assert from 'node:assert/strict'
import test from 'node:test'

import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'

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
} = {}): Registered & {
  pi: any
  ctx: any
  confirmations: { count: number }
  merges: { count: number }
  status: Record<string, any>
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
  const pi = {
    on(name: string, handler: (...args: any[]) => Promise<any>) {
      handlers.set(name, handler)
    },
    registerTool(tool: any) {
      tools.set(tool.name, tool)
    },
    registerCommand(name: string, command: any) {
      commands.set(name, command)
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
        return { code: 0, stdout: `${'p'.repeat(40)}\n`, stderr: '' }
      }
      assert.equal(command, 'python3')
      if (args.includes('status')) return { code: 0, stdout: JSON.stringify(status), stderr: '' }
      if (args.includes('lease') && args.includes('acquire')) {
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
    mode: 'tui',
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
  return { handlers, tools, commands, pi, ctx, confirmations, merges, status }
}

test('injects a fresh control snapshot before every agent turn', async () => {
  const { handlers, ctx, status } = harness()
  const handler = handlers.get('before_agent_start')
  assert.ok(handler)
  const first = await handler({ systemPrompt: 'base' }, ctx)
  assert.match(first.systemPrompt, /EASYAUDIT OMP CONTROL SNAPSHOT/)
  assert.match(first.systemPrompt, /phase=IMPLEMENTATION/)
  assert.match(first.systemPrompt, /protection_mode=read-only-no-go/)
  status.phase = 'FINAL_REVIEW'
  status.head = 'c'.repeat(40)
  const second = await handler({ systemPrompt: 'base' }, ctx)
  assert.match(second.systemPrompt, /phase=FINAL_REVIEW/)
  assert.match(second.systemPrompt, new RegExp(`head=${'c'.repeat(40)}`))
})

test('blocks model-facing mutation when the helper refuses it', async () => {
  const { handlers, ctx } = harness()
  const handler = handlers.get('tool_call')
  assert.ok(handler)
  const result = await handler({ toolName: 'bash', input: { command: 'true' } }, ctx)
  assert.deepEqual(result, { block: true, reason: 'no writer lease' })
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
  ]) {
    assert.ok(tools.has(name), `missing tool ${name}`)
  }
  for (const name of ['ea-status', 'ea-preflight', 'ea-next']) {
    assert.ok(commands.has(name), `missing command ${name}`)
  }
})

test('cancelled human merge challenge performs no action', async () => {
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
    tool.execute(
      'call',
      { pr: 44, expectedHead: 'a'.repeat(40) },
      undefined,
      undefined,
      ctx,
    ),
    /authorization was not granted/,
  )
  assert.equal(confirmations.count, 1)
  assert.equal(merges.count, 0)
  await sessionShutdown({}, ctx)
})

test('human merge confirmation is consumed inside each exact action', async () => {
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
    await tool.execute(
      `call-${index}`,
      { pr: 44, expectedHead: 'a'.repeat(40) },
      undefined,
      undefined,
      ctx,
    )
  }
  assert.equal(confirmations.count, 2)
  assert.equal(merges.count, 2)
  await sessionShutdown({}, ctx)
})
