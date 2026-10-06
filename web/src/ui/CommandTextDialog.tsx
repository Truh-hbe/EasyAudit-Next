import { Alert, Button, Drawer, Flex, Form, Grid, Input, Modal, Typography } from 'antd'
import type { InputRef } from 'antd'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { failureAlertType } from '../product/commandFailure'
import type { CommandFailure, CommandResult } from '../product/commandFailure'
import { FieldError } from './FieldError'

export interface CommandTextDialogProps {
  container: 'modal' | 'drawer'
  open: boolean
  onClose: () => void
  title: string
  description?: ReactNode
  // 服务端 422 提示里的字段名（如 root_cause），用于把提示挂到输入框上。
  fieldName: string
  fieldLabel: string
  placeholder?: string
  okText: string
  danger?: boolean
  run: (text: string) => Promise<CommandResult>
}

// 需要一段文字的业务操作：普通编辑用 Drawer，需要原因的确认用 Modal。
// 失败时弹层保持打开并保留已填内容；请求进行中不能关闭，避免结果无处呈现。
export function CommandTextDialog({
  container,
  open,
  onClose,
  title,
  description,
  fieldName,
  fieldLabel,
  placeholder,
  okText,
  danger,
  run,
}: CommandTextDialogProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<{ text?: string }>()
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<CommandFailure | null>(null)
  const submittingRef = useRef(false)
  const inputRef = useRef<InputRef>(null)
  const fieldError = failure?.fieldErrors[fieldName]

  // 每次打开、关闭或卸载都换一个编辑会话：晚到的结果只影响发起它的会话，不能关闭或污染后来打开的弹层。
  const sessionRef = useRef(0)
  useEffect(() => {
    sessionRef.current += 1
    if (open) setFailure(null)
    return () => {
      sessionRef.current += 1
    }
  }, [open])

  useEffect(() => {
    if (fieldError !== undefined) inputRef.current?.focus()
  }, [failure, fieldError])

  async function submit(values: { text?: string }) {
    if (submittingRef.current) return
    submittingRef.current = true
    const session = sessionRef.current
    setSubmitting(true)
    setFailure(null)
    let result: CommandResult
    try {
      result = await run(values.text ?? '')
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
    if (sessionRef.current !== session) return
    if (result.ok) onClose()
    else if (result.failure.kind !== 'busy' && result.failure.kind !== 'session') setFailure(result.failure)
  }

  const body = (
    <Form
      form={form}
      layout="vertical"
      requiredMark={false}
      preserve={false}
      disabled={submitting}
      onValuesChange={() => setFailure((current) => (current === null ? null : { ...current, fieldErrors: {} }))}
      onFinish={(values) => void submit(values)}
    >
      {description === undefined ? null : (
        <Typography.Paragraph type="secondary">{description}</Typography.Paragraph>
      )}
      {failure === null || failure.message === '' ? null : (
        <Alert type={failureAlertType(failure)} showIcon title={failure.message} style={{ marginBottom: 16 }} />
      )}
      <Form.Item
        label={fieldLabel}
        name="text"
        validateStatus={fieldError === undefined ? undefined : 'error'}
        help={fieldError === undefined ? undefined : <FieldError>{fieldError}</FieldError>}
      >
        <Input.TextArea ref={inputRef} rows={4} placeholder={placeholder} />
      </Form.Item>
      <Flex justify="flex-end" gap={8}>
        <Button onClick={onClose} disabled={submitting}>
          取消
        </Button>
        <Button type="primary" danger={danger} htmlType="submit" loading={submitting}>
          {okText}
        </Button>
      </Flex>
    </Form>
  )

  const lock = { mask: { closable: !submitting }, keyboard: !submitting, closable: !submitting }
  if (container === 'drawer') {
    return (
      <Drawer title={title} open={open} onClose={onClose} size={screens.sm ? 480 : '100%'} destroyOnHidden {...lock}>
        {body}
      </Drawer>
    )
  }
  return (
    <Modal title={title} open={open} onCancel={onClose} footer={null} destroyOnHidden {...lock}>
      {body}
    </Modal>
  )
}
