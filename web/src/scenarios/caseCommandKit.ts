import type { ReviewCaseLifecycle } from '../api/product'
import type { ScenarioCaseCommand } from './registry'

// 活动命令的共用定义：各场景适配器按自己的生命周期规则选用（两个 v1 场景的活动流转相同，规则仍属于各自场景）。
// 只列出该状态下可能合法的命令；角色是否允许由服务器判断。

const SCHEDULE: ScenarioCaseCommand = {
  action: 'schedule',
  label: '安排活动',
  buttonText: '安排活动',
  primary: true,
  mode: 'direct',
}

const START: ScenarioCaseCommand = {
  action: 'start',
  label: '开始活动',
  buttonText: '开始活动',
  primary: true,
  mode: 'direct',
}

const FINISH_FIELDWORK: ScenarioCaseCommand = {
  action: 'finish_fieldwork',
  label: '完成现场工作',
  buttonText: '完成现场工作',
  primary: true,
  mode: 'confirm',
  dialogTitle: '完成现场工作',
  dialogDescription: '完成后活动进入待关闭，不能再新建发现项；如需补录，可在待关闭时带原因恢复现场。',
  okText: '确认完成',
}

const REOPEN_FIELDWORK: ScenarioCaseCommand = {
  action: 'reopen_fieldwork',
  label: '恢复现场',
  buttonText: '恢复现场',
  mode: 'reason',
  dialogTitle: '恢复现场',
  dialogDescription: '恢复后活动回到审查中，可继续新建发现项；请说明恢复原因（如误操作或需要补录）。',
  okText: '确认恢复',
  reasonLabel: '恢复原因',
}

const CLOSE: ScenarioCaseCommand = {
  action: 'close',
  label: '关闭活动',
  buttonText: '关闭活动',
  primary: true,
  mode: 'confirm',
  dialogTitle: '关闭活动',
  dialogDescription: '关闭后活动不可再修改。需要所有发现项均已关闭或作废，否则服务器会拒绝。',
  okText: '确认关闭',
}

const CANCEL: ScenarioCaseCommand = {
  action: 'cancel',
  label: '取消活动',
  buttonText: '取消活动',
  danger: true,
  mode: 'reason',
  dialogTitle: '取消活动',
  dialogDescription: '取消后活动不能恢复，请说明取消原因。',
  okText: '确认取消',
  reasonLabel: '取消原因',
}

export function standardCaseCommands(lifecycle: ReviewCaseLifecycle): readonly ScenarioCaseCommand[] {
  switch (lifecycle) {
    case 'draft':
      return [SCHEDULE, CANCEL]
    case 'scheduled':
      return [START, CANCEL]
    case 'in_progress':
      return [FINISH_FIELDWORK]
    case 'awaiting_closure':
      return [REOPEN_FIELDWORK, CLOSE]
    default:
      return []
  }
}

export function standardCanCreateFinding(lifecycle: ReviewCaseLifecycle): boolean {
  return lifecycle === 'in_progress'
}
