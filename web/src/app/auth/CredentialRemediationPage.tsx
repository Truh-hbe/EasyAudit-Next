import { Alert, Button, Card, Flex, Form, Input } from 'antd'
import { useState } from 'react'

import { changeOwnPassword } from '../../api/auth'
import { ApiError } from '../../api/client'
import { FieldError } from '../../ui/FieldError'
import { LogoutButton } from './LogoutButton'
import { useSession } from './session'

interface PasswordValues {
  current_password: string
  new_password: string
  confirmation: string
}

export function CredentialRemediationPage() {
  const { state, refresh } = useSession()
  const [form] = Form.useForm<PasswordValues>()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (state.status !== 'authenticated') {
    return null
  }

  async function submit(values: PasswordValues) {
    if (submitting) {
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await changeOwnPassword({
        current_password: values.current_password,
        new_password: values.new_password,
      })
      form.resetFields()
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
    <Flex component="main" aria-labelledby="remediation-title" justify="center" align="center" className="auth-page">
      <Card className="auth-panel">
        <Flex vertical gap={16}>
          <Flex vertical gap={8}>
            <h1 id="remediation-title">需要修改密码</h1>
            <p>{state.user.display_name}，服务器要求先完成密码修改，再进入业务界面。</p>
          </Flex>
          {error === null ? null : <Alert type="error" showIcon title={error} />}
          <Form form={form} layout="vertical" requiredMark={false} scrollToFirstError={{ focus: true }} onFinish={(values) => void submit(values)}>
            <Form.Item
              label="当前密码"
              name="current_password"
              rules={[{ required: true, message: <FieldError>请输入当前密码</FieldError> }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Form.Item
              label="新密码"
              name="new_password"
              rules={[{ required: true, message: <FieldError>请输入新密码</FieldError> }]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              label="确认新密码"
              name="confirmation"
              dependencies={['new_password']}
              rules={[
                { required: true, message: <FieldError>请再次输入新密码</FieldError> },
                ({ getFieldValue }) => ({
                  message: <FieldError>两次输入的新密码不一致</FieldError>,
                  validator: (_, value: string | undefined) =>
                    value === undefined || value === '' || value === getFieldValue('new_password')
                      ? Promise.resolve()
                      : Promise.reject(new Error()),
                }),
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting}>
              修改密码
            </Button>
          </Form>
          <LogoutButton block />
        </Flex>
      </Card>
    </Flex>
  )
}
