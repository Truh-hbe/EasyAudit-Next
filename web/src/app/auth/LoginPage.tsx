import { Alert, Button, Card, Flex, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { useLocation } from 'react-router'

import { loginWithPassword } from '../../api/auth'
import { ApiError } from '../../api/client'
import { FieldError } from '../../ui/FieldError'
import { useSession } from './session'

function hasUnconfirmedLogout(state: unknown): boolean {
  return (
    typeof state === 'object' &&
    state !== null &&
    'logoutUnconfirmed' in state &&
    (state as { logoutUnconfirmed?: unknown }).logoutUnconfirmed === true
  )
}

export function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return '登录名或密码无效'
    }
    if (error.status === 429) {
      if (error.retryAfter !== null && error.retryAfter > 0) {
        const minutes = Math.ceil(error.retryAfter / 60)
        return `登录尝试过于频繁，请约 ${minutes} 分钟后再试。`
      }
      return '登录尝试过于频繁，请稍后再试。'
    }
  }
  return '暂时无法完成登录，请重试'
}

interface LoginValues {
  login_name: string
  password: string
}

export function LoginPage() {
  const { refresh } = useSession()
  const location = useLocation()
  const [form] = Form.useForm<LoginValues>()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(values: LoginValues) {
    if (submitting) {
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await loginWithPassword(values.login_name, values.password)
      form.setFieldValue('password', '')
      await refresh()
    } catch (caught) {
      setError(loginErrorMessage(caught))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Flex component="main" aria-labelledby="login-title" justify="center" align="center" className="auth-page">
      <Card className="auth-panel">
        <Flex vertical gap={16}>
          <Flex vertical gap={4}>
            <Typography.Text>EasyAudit Next</Typography.Text>
            <h1 id="login-title">登录</h1>
          </Flex>
          {hasUnconfirmedLogout(location.state) ? (
            <Alert
              type="warning"
              showIcon
              role="status"
              title="本地受保护界面已清除，但服务器退出状态未能确认。"
            />
          ) : null}
          {error === null ? null : <Alert type="error" showIcon title={error} />}
          <Form form={form} layout="vertical" requiredMark={false} scrollToFirstError={{ focus: true }} onFinish={(values) => void submit(values)}>
            <Form.Item
              label="登录名"
              name="login_name"
              rules={[{ required: true, message: <FieldError>请输入登录名</FieldError> }]}
            >
              <Input autoComplete="username" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: <FieldError>请输入密码</FieldError> }]}>
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting} autoInsertSpace={false}>
              登录
            </Button>
          </Form>
        </Flex>
      </Card>
    </Flex>
  )
}
