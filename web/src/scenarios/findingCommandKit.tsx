import { CheckOutlined, EditOutlined, RollbackOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'
import { App, Button, Card, Flex, Typography } from 'antd'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { CommandTextDialog } from '../ui/CommandTextDialog'
import type { ScenarioFindingInteractionProps } from './registry'

// 发现项业务操作的共用部件：各场景适配器按自己的生命周期规则选用，核心页面不感知场景。

type CommandProps = Pick<ScenarioFindingInteractionProps, 'commands' | 'execute' | 'disabled'>

export function FindingCommandCard({ scenarioLabel, children }: { scenarioLabel: string; children: ReactNode }) {
  return (
    <section aria-labelledby="finding-command-title">
      <Card title={<h2 id="finding-command-title">业务操作</h2>}>
        <Flex vertical gap={12}>
          <Typography.Text type="secondary">
            以下操作按{scenarioLabel}场景展示；最终授权、状态与并发判断以服务器为准。
          </Typography.Text>
          {children}
        </Flex>
      </Card>
    </section>
  )
}

export function CommandRow({ children }: { children: ReactNode }) {
  return (
    <Flex wrap gap={8}>
      {children}
    </Flex>
  )
}

export function CommandNote({ children }: { children: ReactNode }) {
  return <Typography.Text type="secondary">{children}</Typography.Text>
}

export function VoidCommand({ commands, execute, disabled }: CommandProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        danger
        icon={<StopOutlined aria-hidden />}
        data-scenario-action="void"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        作废发现项
      </Button>
      <CommandTextDialog
        container="modal"
        open={open}
        onClose={() => setOpen(false)}
        title="作废发现项"
        description="作废后发现项不能恢复，请说明作废原因。"
        fieldName="reason"
        fieldLabel="作废原因"
        okText="确认作废"
        danger
        run={(reason) => execute('作废发现项', () => commands.transition('void', reason), { fields: ['reason'], notify: false })}
      />
    </>
  )
}

export function ReopenCommand({ commands, execute, disabled }: CommandProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        icon={<RollbackOutlined aria-hidden />}
        data-scenario-action="reopen"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        重新打开
      </Button>
      <CommandTextDialog
        container="modal"
        open={open}
        onClose={() => setOpen(false)}
        title="重新打开发现项"
        description="重新打开后发现项回到整改中，请说明原因。"
        fieldName="reason"
        fieldLabel="重新打开原因"
        okText="确认重新打开"
        run={(reason) => execute('重新打开发现项', () => commands.reopen(reason), { fields: ['reason'], notify: false })}
      />
    </>
  )
}

// 整改中：整改计划与整改完成是两次独立提交，各自一个抽屉。
export function RectificationCommands({ commands, execute, disabled }: CommandProps) {
  const [planOpen, setPlanOpen] = useState(false)
  const [completionOpen, setCompletionOpen] = useState(false)
  return (
    <>
      <Button
        icon={<EditOutlined aria-hidden />}
        data-scenario-action="submit_plan"
        disabled={disabled}
        onClick={() => setPlanOpen(true)}
      >
        填写整改计划
      </Button>
      <Button
        type="primary"
        icon={<SendOutlined aria-hidden />}
        data-scenario-action="submit_for_verification"
        disabled={disabled}
        onClick={() => setCompletionOpen(true)}
      >
        提交整改完成
      </Button>
      <CommandTextDialog
        container="drawer"
        open={planOpen}
        onClose={() => setPlanOpen(false)}
        title="整改计划"
        fieldName="root_cause"
        fieldLabel="根本原因"
        placeholder="必填规则由服务器校验"
        okText="提交整改计划"
        run={(rootCause) =>
          execute(
            '提交整改计划',
            () => commands.submitRectification('submit_plan', { stage: 'plan', root_cause: rootCause }),
            { fields: ['root_cause'], notify: false },
          )
        }
      />
      <CommandTextDialog
        container="drawer"
        open={completionOpen}
        onClose={() => setCompletionOpen(false)}
        title="整改完成"
        description="提交后发现项进入待验证；服务器会校验所有未取消的整改项均已完成。"
        fieldName="comment"
        fieldLabel="整改完成说明"
        okText="提交验证"
        run={(comment) =>
          execute(
            '提交验证',
            () => commands.submitRectification('submit_for_verification', { stage: 'completion', comment }),
            { fields: ['comment'], notify: false },
          )
        }
      />
    </>
  )
}

// 待验证：通过验证直接执行；驳回需要原因，在确认框里填写。
export function VerificationCommands({ commands, execute, disabled }: CommandProps) {
  const [rejectOpen, setRejectOpen] = useState(false)
  return (
    <>
      <Button
        type="primary"
        icon={<CheckOutlined aria-hidden />}
        data-scenario-action="approve"
        disabled={disabled}
        onClick={() =>
          void execute('验证通过', () => commands.submitVerification('approve', { result: 'approved' }))
        }
      >
        通过验证
      </Button>
      <Button
        icon={<RollbackOutlined aria-hidden />}
        data-scenario-action="reject"
        disabled={disabled}
        onClick={() => setRejectOpen(true)}
      >
        驳回验证
      </Button>
      <CommandTextDialog
        container="modal"
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="驳回验证"
        description="驳回后发现项回到整改中，请说明驳回原因。"
        fieldName="comment"
        fieldLabel="驳回原因"
        okText="确认驳回"
        run={(comment) =>
          execute(
            '验证驳回',
            () => commands.submitVerification('reject', { result: 'rejected', comment }),
            { fields: ['comment'], notify: false },
          )
        }
      />
    </>
  )
}

interface ConfirmedCommandProps extends CommandProps {
  action: string
  label: string
  buttonText: string
  confirmTitle: string
  confirmContent: string
  confirmOkText: string
  run: () => Promise<unknown>
  primary?: boolean
}

// 不可逆的直接操作（如接受观察项）：二次确认；失败由页面提示呈现，确认框总是正常结束。
export function ConfirmedCommand({
  execute,
  disabled,
  action,
  label,
  buttonText,
  confirmTitle,
  confirmContent,
  confirmOkText,
  run,
  primary,
}: ConfirmedCommandProps) {
  const { modal } = App.useApp()
  return (
    <Button
      type={primary === true ? 'primary' : 'default'}
      icon={<CheckOutlined aria-hidden />}
      data-scenario-action={action}
      disabled={disabled}
      onClick={() =>
        modal.confirm({
          title: confirmTitle,
          content: confirmContent,
          okText: confirmOkText,
          cancelText: '取消',
          onOk: async () => {
            await execute(label, run)
          },
        })
      }
    >
      {buttonText}
    </Button>
  )
}

// 直接执行、不需要确认或输入的操作（如签发）。
export function DirectCommand({
  execute,
  disabled,
  action,
  label,
  buttonText,
  run,
  primary,
}: Pick<ConfirmedCommandProps, 'execute' | 'disabled' | 'action' | 'label' | 'buttonText' | 'run' | 'primary'>) {
  return (
    <Button
      type={primary === true ? 'primary' : 'default'}
      data-scenario-action={action}
      disabled={disabled}
      onClick={() => void execute(label, run)}
    >
      {buttonText}
    </Button>
  )
}
