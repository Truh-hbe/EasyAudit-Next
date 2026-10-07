import { Alert, Button, Card, Flex, Typography } from 'antd'
import { useState } from 'react'

import { failureAlertType } from '../../product/commandFailure'
import type { CommandFailure, CommandResult } from '../../product/commandFailure'
import type { ScenarioCaseCommand } from '../../scenarios/registry'
import { CommandTextDialog } from '../../ui/CommandTextDialog'
import { useConfirm } from '../../ui/useConfirm'

type RunCommand = (command: ScenarioCaseCommand, reason?: string) => Promise<CommandResult>

interface CommandButtonProps {
  command: ScenarioCaseCommand
  disabled: boolean
  run: RunCommand
}

// 确认框与原因弹层由各自按钮持有：整个卡片随主授权丢失（页面改为 Result）或 lifecycle 变化而卸载，不会留下可提交的浮层。
function CaseCommandButton({ command, disabled, run }: CommandButtonProps) {
  const { confirm } = useConfirm()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        type={command.primary === true ? 'primary' : 'default'}
        danger={command.danger}
        data-case-action={command.action}
        disabled={disabled}
        onClick={() => {
          if (command.mode === 'direct') {
            void run(command)
          } else if (command.mode === 'confirm') {
            confirm({
              title: command.dialogTitle ?? command.buttonText,
              content: command.dialogDescription,
              okText: command.okText ?? '确认',
              cancelText: '取消',
              onOk: async () => {
                await run(command)
              },
            })
          } else {
            setOpen(true)
          }
        }}
      >
        {command.buttonText}
      </Button>
      {command.mode === 'reason' ? (
        <CommandTextDialog
          container="modal"
          open={open}
          onClose={() => setOpen(false)}
          title={command.dialogTitle ?? command.buttonText}
          description={command.dialogDescription}
          fieldName="reason"
          fieldLabel={command.reasonLabel ?? '原因'}
          okText={command.okText ?? '确认'}
          danger={command.danger}
          run={(reason) => run(command, reason)}
        />
      ) : null}
    </>
  )
}

export function CaseLifecycleCommands({ commands, busy, notice, onDismissNotice, run }: {
  commands: readonly ScenarioCaseCommand[]
  busy: boolean
  notice: CommandFailure | null
  onDismissNotice: () => void
  run: RunCommand
}) {
  return (
    <section aria-labelledby="case-commands-title">
      <Card title={<h2 id="case-commands-title">活动操作</h2>}>
        <Flex vertical gap={12}>
          <Typography.Text type="secondary">
            以下按当前状态列出可能的操作；最终授权、状态与并发判断以服务器为准。
          </Typography.Text>
          {notice === null || notice.kind === 'session' || notice.message === '' ? null : (
            <Alert
              type={failureAlertType(notice)}
              showIcon
              role="status"
              title={notice.message}
              closable={{ onClose: onDismissNotice }}
            />
          )}
          {commands.length === 0 ? (
            <Typography.Text type="secondary">当前状态没有可执行的操作。</Typography.Text>
          ) : (
            <Flex wrap gap={8}>
              {commands.map((command) => (
                <CaseCommandButton key={command.action} command={command} disabled={busy} run={run} />
              ))}
            </Flex>
          )}
        </Flex>
      </Card>
    </section>
  )
}
