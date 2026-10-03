// 审查活动详情页的主授权状态机（纯函数）。页面只负责派发事件、执行返回的副作用指令。
//
// 规则（docs/design.md「交互状态」：权限丢失时立即移除受保护内容）：
// 1. load（活动变化或用户重新加载）：generation + 1，状态回到 loading，inFlight/dirty 清零。
//    所有响应和触发都带发出时的 generation，不匹配的一律丢弃——拒绝也一样。
// 2. 主读取响应（generation 匹配）：
//    - denied（403/404）：同一 generation 内粘性，之后任何成功或失败都不能恢复；停止补读，发出 remove-protected；
//    - ok：只在不是 denied 时变为 authorized；
//    - error（500/网络）：不改状态，静默重读的失败不移除内容；
//    收到响应后 inFlight = false；若期间有新触发（dirty）且未 denied，立即补读一次。
// 3. trigger（团队写操作成功，或与主授权同语义的从属接口返回 403/404）：denied 或 loading 时忽略；
//    inFlight 时只标记 dirty，否则发出一次重读。管理进度的 403/404 是额外的权限边界，调用方不得派发 trigger。

export type CaseAuthorizationStatus = 'loading' | 'authorized' | 'denied'

export interface CaseAuthorizationState {
  generation: number
  status: CaseAuthorizationStatus
  inFlight: boolean
  dirty: boolean
}

export type CaseAuthorizationEvent =
  | { type: 'load' }
  | { type: 'trigger'; generation: number }
  | { type: 'response'; generation: number; result: 'ok' | 'denied' | 'error' }

// start-recheck：对当前 generation 发一次静默主读取；remove-protected：移除全部受保护内容。
export type CaseAuthorizationEffect = 'start-recheck' | 'remove-protected'

export const initialCaseAuthorization: CaseAuthorizationState = {
  generation: 0,
  status: 'loading',
  inFlight: false,
  dirty: false,
}

export function reduceCaseAuthorization(
  state: CaseAuthorizationState,
  event: CaseAuthorizationEvent,
): { state: CaseAuthorizationState; effects: CaseAuthorizationEffect[] } {
  if (event.type === 'load') {
    return {
      state: { generation: state.generation + 1, status: 'loading', inFlight: false, dirty: false },
      effects: [],
    }
  }

  if (event.generation !== state.generation) return { state, effects: [] }

  if (event.type === 'trigger') {
    if (state.status !== 'authorized') return { state, effects: [] }
    if (state.inFlight) return { state: { ...state, dirty: true }, effects: [] }
    return { state: { ...state, inFlight: true }, effects: ['start-recheck'] }
  }

  if (event.result === 'denied') {
    return {
      state: { ...state, status: 'denied', inFlight: false, dirty: false },
      effects: state.status === 'denied' ? [] : ['remove-protected'],
    }
  }

  const status = state.status === 'denied' ? 'denied' : event.result === 'ok' ? 'authorized' : state.status
  if (state.dirty && status === 'authorized') {
    return { state: { ...state, status, inFlight: true, dirty: false }, effects: ['start-recheck'] }
  }
  return { state: { ...state, status, inFlight: false, dirty: false }, effects: [] }
}
