import { Alert, Button, Drawer, Flex, Form, Grid, Input, Typography } from 'antd'
import type { InputRef } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { failureAlertType } from '../../product/commandFailure'
import type { CommandFailure, CommandResult } from '../../product/commandFailure'
import {
  DISPLAY_TIME_ZONE_HINT,
  invalidDisplayZoneInputMessage,
  parseOptionalDisplayZoneText,
} from '../../product/format'
import { FieldError } from '../../ui/FieldError'
import { ShanghaiDateTimePicker } from '../../ui/ShanghaiDateTimePicker'

const TIME_ZONE_HINT_ID = 'action-due-time-zone-hint'

export interface ActionCreateInput {
  title: string
  due_at: string | null
}

interface ActionCreateDrawerProps {
  open: boolean
  onClose: () => void
  create: (input: ActionCreateInput) => Promise<CommandResult>
}

interface FormValues {
  title?: string
  due_at?: string
}

// 新建整改项：到期时间是 `YYYY/MM/DD HH:mm` 的上海时间文本，转换成 ISO 在提交时进行；
// 服务端 422 能对应字段的挂在字段上，其余显示在弹层顶部；失败时保留已填内容。
export function ActionCreateDrawer({ open, onClose, create }: ActionCreateDrawerProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<CommandFailure | null>(null)
  const submittingRef = useRef(false)
  const titleRef = useRef<InputRef>(null)
  const titleError = failure?.fieldErrors.title
  const dueError = failure?.fieldErrors.due_at

  useEffect(() => {
    if (open) setFailure(null)
  }, [open])

  useEffect(() => {
    if (titleError !== undefined) titleRef.current?.focus()
  }, [failure, titleError])

  async function submit(values: FormValues) {
    if (submittingRef.current) return
    const due = parseOptionalDisplayZoneText(values.due_at ?? '')
    // 无效文本已由字段规则拦截；这里只是为类型收窄。
    if (!due.valid) return
    submittingRef.current = true
    setSubmitting(true)
    setFailure(null)
    let result: CommandResult
    try {
      result = await create({ title: values.title ?? '', due_at: due.iso })
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
    if (result.ok) onClose()
    else if (result.failure.kind !== 'busy' && result.failure.kind !== 'session') setFailure(result.failure)
  }

  return (
    <Drawer
      title="新建整改项"
      open={open}
      onClose={onClose}
      size={screens.sm ? 480 : '100%'}
      destroyOnHidden
      mask={{ closable: !submitting }}
      closable={!submitting}
      keyboard={!submitting}
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        preserve={false}
        disabled={submitting}
        onValuesChange={() => setFailure((current) => (current === null ? null : { ...current, fieldErrors: {} }))}
        onFinish={(values) => void submit(values)}
      >
        {failure === null || failure.message === '' ? null : (
          <Alert type={failureAlertType(failure)} showIcon title={failure.message} style={{ marginBottom: 16 }} />
        )}
        <Form.Item
          label="标题"
          name="title"
          validateStatus={titleError === undefined ? undefined : 'error'}
          help={titleError === undefined ? undefined : <FieldError>{titleError}</FieldError>}
        >
          <Input ref={titleRef} autoComplete="off" />
        </Form.Item>
        <Typography.Paragraph id={TIME_ZONE_HINT_ID} type="secondary">
          {DISPLAY_TIME_ZONE_HINT}
        </Typography.Paragraph>
        <Form.Item
          label="到期时间"
          name="due_at"
          validateStatus={dueError === undefined ? undefined : 'error'}
          help={dueError === undefined ? undefined : <FieldError>{dueError}</FieldError>}
          rules={[
            {
              validator: (_, value: string | undefined) =>
                parseOptionalDisplayZoneText(value ?? '').valid
                  ? Promise.resolve()
                  : Promise.reject(<FieldError>{invalidDisplayZoneInputMessage('到期时间')}</FieldError>),
            },
          ]}
        >
          <ShanghaiDateTimePicker hintId={TIME_ZONE_HINT_ID} />
        </Form.Item>
        <Flex justify="flex-end" gap={8}>
          <Button onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            创建整改项
          </Button>
        </Flex>
      </Form>
    </Drawer>
  )
}
