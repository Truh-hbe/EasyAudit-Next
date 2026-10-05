import { describe, expect, it } from 'vitest'

import { initialCaseAuthorization, reduceCaseAuthorization } from './caseAuthorization'
import type { CaseAuthorizationEffect, CaseAuthorizationEvent, CaseAuthorizationState } from './caseAuthorization'

// 依次应用事件，返回最终状态和每一步发出的指令。
function run(events: CaseAuthorizationEvent[], from: CaseAuthorizationState = initialCaseAuthorization) {
  let state = from
  const effects: CaseAuthorizationEffect[][] = []
  for (const event of events) {
    const result = reduceCaseAuthorization(state, event)
    state = result.state
    effects.push(result.effects)
  }
  return { state, effects }
}

// 已加载并授权的 generation 1。
const authorized = run([{ type: 'load' }, { type: 'response', generation: 1, result: 'ok' }]).state

describe('case authorization state machine', () => {
  it('load bumps the generation and clears inFlight and dirty', () => {
    const busy = run([{ type: 'trigger', generation: 1 }, { type: 'trigger', generation: 1 }], authorized).state
    expect(busy).toMatchObject({ inFlight: true, dirty: true })
    expect(run([{ type: 'load' }], busy).state).toEqual({ generation: 2, status: 'loading', inFlight: false, dirty: false })
  })

  it('a trigger while authorized starts exactly one recheck', () => {
    const { state, effects } = run([{ type: 'trigger', generation: 1 }], authorized)
    expect(effects).toEqual([['start-recheck']])
    expect(state.inFlight).toBe(true)
  })

  it('repeated triggers while in flight coalesce into a single follow-up recheck', () => {
    const { state, effects } = run(
      [
        { type: 'trigger', generation: 1 },
        { type: 'trigger', generation: 1 },
        { type: 'trigger', generation: 1 },
        { type: 'response', generation: 1, result: 'ok' },
        { type: 'response', generation: 1, result: 'ok' },
      ],
      authorized,
    )
    expect(effects).toEqual([['start-recheck'], [], [], ['start-recheck'], []])
    expect(state).toMatchObject({ status: 'authorized', inFlight: false, dirty: false })
  })

  it('a trigger that arrives during a recheck that then returns 200 is replayed, and the replay can deny', () => {
    const { state, effects } = run(
      [
        { type: 'trigger', generation: 1 },
        { type: 'trigger', generation: 1 },
        { type: 'response', generation: 1, result: 'ok' },
        { type: 'response', generation: 1, result: 'denied' },
      ],
      authorized,
    )
    expect(effects).toEqual([['start-recheck'], [], ['start-recheck'], ['remove-protected']])
    expect(state.status).toBe('denied')
  })

  it('the follow-up recheck also runs when the earlier one failed with a network or 5xx error', () => {
    const { effects, state } = run(
      [
        { type: 'trigger', generation: 1 },
        { type: 'trigger', generation: 1 },
        { type: 'response', generation: 1, result: 'error' },
      ],
      authorized,
    )
    expect(effects[2]).toEqual(['start-recheck'])
    expect(state.status).toBe('authorized')
  })

  it('denied is sticky within a generation: later ok, error, denied or triggers change nothing', () => {
    const denied = run([{ type: 'trigger', generation: 1 }, { type: 'response', generation: 1, result: 'denied' }], authorized)
    expect(denied.effects[1]).toEqual(['remove-protected'])
    const after = run(
      [
        { type: 'response', generation: 1, result: 'ok' },
        { type: 'response', generation: 1, result: 'error' },
        { type: 'response', generation: 1, result: 'denied' },
        { type: 'trigger', generation: 1 },
      ],
      denied.state,
    )
    expect(after.state.status).toBe('denied')
    expect(after.effects).toEqual([[], [], [], []])
  })

  it('a pending dirty flag is dropped when the response denies', () => {
    const { state, effects } = run(
      [
        { type: 'trigger', generation: 1 },
        { type: 'trigger', generation: 1 },
        { type: 'response', generation: 1, result: 'denied' },
      ],
      authorized,
    )
    expect(effects[2]).toEqual(['remove-protected'])
    expect(state).toMatchObject({ status: 'denied', inFlight: false, dirty: false })
  })

  it('a stale generation 403 landing on a newer load is discarded', () => {
    const { state, effects } = run(
      [
        { type: 'trigger', generation: 1 },
        { type: 'load' },
        { type: 'response', generation: 1, result: 'denied' },
        { type: 'response', generation: 2, result: 'ok' },
      ],
      authorized,
    )
    expect(effects).toEqual([['start-recheck'], [], [], []])
    expect(state).toMatchObject({ generation: 2, status: 'authorized' })
  })

  it('stale triggers are ignored', () => {
    const { state, effects } = run([{ type: 'load' }, { type: 'trigger', generation: 1 }], authorized)
    expect(effects).toEqual([[], []])
    expect(state.inFlight).toBe(false)
  })

  it('an error response keeps the status and allows later triggers', () => {
    const { state, effects } = run(
      [
        { type: 'trigger', generation: 1 },
        { type: 'response', generation: 1, result: 'error' },
        { type: 'trigger', generation: 1 },
      ],
      authorized,
    )
    expect(effects).toEqual([['start-recheck'], [], ['start-recheck']])
    expect(state).toMatchObject({ status: 'authorized', inFlight: true })
  })

  it('triggers during the initial load are ignored; a denied initial response removes content', () => {
    const loading = run([{ type: 'load' }]).state
    expect(run([{ type: 'trigger', generation: 1 }], loading).effects).toEqual([[]])
    const { state, effects } = run([{ type: 'response', generation: 1, result: 'denied' }], loading)
    expect(effects).toEqual([['remove-protected']])
    expect(state.status).toBe('denied')
  })

  it('an initial load error leaves the status loading so the page can offer a retry', () => {
    const loading = run([{ type: 'load' }]).state
    expect(run([{ type: 'response', generation: 1, result: 'error' }], loading).state.status).toBe('loading')
  })
})
