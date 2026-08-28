import { type FormEvent, useState } from 'react'
import { useLocation } from 'react-router'

import { loginWithPassword } from '../../api/auth'
import { ApiError } from '../../api/client'
import { useSession } from './session'

function hasUnconfirmedLogout(state: unknown): boolean {
  return (
    typeof state === 'object' &&
    state !== null &&
    'logoutUnconfirmed' in state &&
    (state as { logoutUnconfirmed?: unknown }).logoutUnconfirmed === true
  )
}

export function LoginPage() {
  const { refresh } = useSession()
  const location = useLocation()
  const [loginName, setLoginName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await loginWithPassword(loginName, password)
      setPassword('')
      await refresh()
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setError('登录名或密码无效')
      } else {
        setError('暂时无法完成登录，请重试')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-card" aria-labelledby="login-title">
      <p className="eyebrow">EasyAudit Next</p>
      <h1 id="login-title">登录</h1>
      {hasUnconfirmedLogout(location.state) ? (
        <p role="status">本地受保护界面已清除，但服务器退出状态未能确认。</p>
      ) : null}
      <form onSubmit={(event) => void submit(event)}>
        <label>
          登录名
          <input
            name="login_name"
            autoComplete="username"
            value={loginName}
            onChange={(event) => setLoginName(event.target.value)}
            required
          />
        </label>
        <label>
          密码
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error === null ? null : <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? '登录中…' : '登录'}
        </button>
      </form>
    </main>
  )
}
