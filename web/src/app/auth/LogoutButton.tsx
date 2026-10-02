import { LogoutOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { logoutCurrentSession } from '../../api/auth'
import { ApiError } from '../../api/client'
import { useSession } from './session'

export function LogoutButton({ className }: { className?: string }) {
  const { clearLocalSession } = useSession()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)

  async function logout() {
    setSubmitting(true)
    try {
      await logoutCurrentSession()
      clearLocalSession()
      navigate('/login', { replace: true })
    } catch (caught) {
      clearLocalSession()
      navigate('/login', {
        replace: true,
        state:
          caught instanceof ApiError && caught.status === 401
            ? undefined
            : { logoutUnconfirmed: true },
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Button
      className={className}
      icon={<LogoutOutlined aria-hidden />}
      disabled={submitting}
      onClick={() => void logout()}
    >
      {submitting ? '退出中…' : '退出登录'}
    </Button>
  )
}
