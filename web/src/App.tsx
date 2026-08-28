import { useSession } from './app/auth/session'

export function App() {
  const { state, resolutionError, refresh } = useSession()

  if (state.status === 'resolving') {
    return (
      <main className="foundation" aria-labelledby="foundation-title">
        <p className="eyebrow">M3.5.1</p>
        <h1 id="foundation-title">正在确认服务器会话</h1>
        <p>受保护界面会在服务器 Session 与凭据状态确认后再决定是否呈现。</p>
        {resolutionError === null ? null : (
          <div role="alert">
            <p>{resolutionError}</p>
            <button type="button" onClick={() => void refresh()}>
              重试
            </button>
          </div>
        )}
      </main>
    )
  }

  if (state.status === 'anonymous') {
    return (
      <main className="foundation" aria-labelledby="foundation-title">
        <p className="eyebrow">M3.5.1</p>
        <h1 id="foundation-title">当前没有有效会话</h1>
        <p>登录交互将在下一可审查增量接入；当前状态来自 GET /api/v1/me。</p>
      </main>
    )
  }

  return (
    <main className="foundation" aria-labelledby="foundation-title">
      <p className="eyebrow">M3.5.1</p>
      <h1 id="foundation-title">服务器会话已确认</h1>
      <p>{state.user.display_name}</p>
      <p>
        凭据状态：{state.user.must_change_password ? '服务器要求修改密码' : '服务器报告已就绪'}
      </p>
    </main>
  )
}
