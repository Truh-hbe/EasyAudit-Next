import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import test from 'node:test'

import * as TypeBox from '@oh-my-pi/omptype/typebox'
import type { ExtensionAPI } from '@oh-my-pi/pi-coding-agent'

import easyauditGuard from './index.js'

function provenanceGuard(
  sourcePath: string,
  baseDir: string | undefined,
): (event: any, ctx: any) => Promise<any> {
  const handlers = new Map<string, (...args: any[]) => Promise<any>>()
  const pi = {
    typebox: TypeBox,
    on(name: string, handler: (...args: any[]) => Promise<any>) {
      handlers.set(name, handler)
    },
    registerTool() {},
    registerCommand() {},
    getAllTools() {
      return [{
        name: 'ea_exec',
        description: 'fixture',
        parameters: {},
        sourceInfo: {
          source: 'extension',
          path: sourcePath,
          baseDir,
          scope: 'project',
          origin: 'top-level',
        },
      }]
    },
    async exec() {
      throw new Error('untrusted provenance must be rejected before helper execution')
    },
  }
  easyauditGuard(pi as unknown as ExtensionAPI)
  const guard = handlers.get('tool_call')
  assert.ok(guard)
  return guard
}

const ctx = {
  mode: 'tui',
  sessionManager: {
    getSessionId: () => 'provenance-test',
    getSessionFile: () => undefined,
  },
  isProjectTrusted: () => true,
  ui: { notify() {}, setStatus() {} },
}

async function expectBlocked(sourcePath: string, baseDir?: string) {
  const guard = provenanceGuard(sourcePath, baseDir)
  const result = await guard({ toolName: 'ea_exec', input: { profile: 'git-status' } }, ctx)
  assert.deepEqual(result, {
    block: true,
    reason: 'EasyAudit control tool provenance is not trusted',
  })
}

test('prefix-collision easyaudit-guard-evil extension is blocked', async () => {
  const sourcePath = resolve(import.meta.dirname, '../easyaudit-guard-evil/index.ts')
  await expectBlocked(sourcePath, dirname(sourcePath))
})

test('same basename from another extension root is blocked', async () => {
  const root = mkdtempSync(join(tmpdir(), 'easyaudit-user-extension-'))
  const baseDir = join(root, 'easyaudit-guard')
  mkdirSync(baseDir)
  const sourcePath = join(baseDir, 'index.ts')
  writeFileSync(sourcePath, 'export default {}\n', 'utf8')
  await expectBlocked(sourcePath, baseDir)
})

test('symlinked fake extension is blocked after realpath resolution', async () => {
  const root = mkdtempSync(join(tmpdir(), 'easyaudit-symlink-extension-'))
  const fakeDir = join(root, 'fake')
  mkdirSync(fakeDir)
  const fakePath = join(fakeDir, 'index.ts')
  writeFileSync(fakePath, 'export default {}\n', 'utf8')
  const linkPath = join(root, 'index.ts')
  symlinkSync(fakePath, linkPath)
  await expectBlocked(linkPath, root)
})

test('exact source path with wrong base directory is blocked', async () => {
  const sourcePath = resolve(import.meta.dirname, 'index.ts')
  await expectBlocked(sourcePath, resolve(import.meta.dirname, '..'))
})
