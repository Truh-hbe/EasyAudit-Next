import { type FormEvent, useState } from 'react'

import { changeOwnPassword } from '../../api/auth'
import { ApiError } from '../../api/client'
import { LogoutButton } from './LogoutButton'
import { useSession } from './session'

export function CredentialRemediationPage() {
  const { state, refresh } = useSession()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (state.status !== 'authenticated') {
    return null
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (newPassword !== confirmation) {
      setError('两次输入的新密码不一致')
      return
    }

    setSubmitting(true)
    try {
      await changeOwnPassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
      await refresh()
    } catch (caught) {
      if (caught instanceof ApiError && [400, 409, 422].includes(caught.status)) {
        setError(caught.detail)
      } else if (!(caught instanceof ApiError && caught.status === 401)) {
        setError('暂时无法修改密码，请重试')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-card" aria-labelledby="remediation-title">
      <p className="eyebrow">已认证 · 凭据整改</p>
      <h1 id="remediation-title">需要修改密码</h1>
      <p>{state.user.display_name}，服务器要求先完成密码修改，再进入业务界面。</p>
      <form onSubmit={(event) => void submit(event)}>
        <label>
          当前密码
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
          />
        </label>
        <label>
          新密码
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
          />
        </label>
        <label>
          确认新密码
          <input
            type="password"
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            required
          />
        </label>
        {error === null ? null : <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? '提交中…' : '修改密码'}
        </button>
      </form>
      <LogoutButton className="secondary" />
    </main>
  )
}
