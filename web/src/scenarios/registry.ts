import type { ComponentType } from 'react'

import type { CommandResult } from '../product/commandFailure'
import type {
  ActionItemLifecycle,
  ActorKind,
  AssignmentRole,
  FindingLifecycle,
  FindingResponse,
  ReviewCaseLifecycle,
  ReviewCaseResponse,
  SubmissionResponse,
} from '../api/product'

export type ScenarioFormValues = Record<string, string>

export interface ScenarioCaseSectionProps {
  reviewCase: ReviewCaseResponse
}

// 场景字段的展示项：由适配器给出标签和文本，核心页面用 Descriptions 统一渲染。
export interface ScenarioDescriptionItem {
  key: string
  label: string
  value: string
}

// 一条历史提交的展示：标题、结论与按场景翻译好的字段；未知字段进入 extras，由页面按纯文本展示。
export interface ScenarioSubmissionField {
  key: string
  label: string
  value: string
}

export interface ScenarioSubmissionView {
  heading: string
  // 验证提交的结论；其他提交为 null。
  outcome: 'approved' | 'rejected' | null
  fields: readonly ScenarioSubmissionField[]
  extras: readonly ScenarioSubmissionField[]
}

export interface ScenarioFormFieldsProps {
  values: ScenarioFormValues
  onChange: (name: string, value: string) => void
  disabled?: boolean
  // 服务端 422 能对应到字段的提示，按字段名索引；只有已迁移到 antd 的表单会传入。
  fieldErrors?: Record<string, string>
}

// 场景声明的活动命令。当前 lifecycle 下"可能合法"的命令清单是状态机，不是权限：
// 角色是否允许由服务器判断，页面不推导。
export interface ScenarioCaseCommand {
  action: string
  // 用于失败提示的操作名，如 "开始活动"。
  label: string
  buttonText: string
  primary?: boolean
  danger?: boolean
  // direct：直接执行；confirm：二次确认；reason：弹层填写原因（服务器校验必填）。
  mode: 'direct' | 'confirm' | 'reason'
  dialogTitle?: string
  dialogDescription?: string
  okText?: string
  reasonLabel?: string
}

export interface ScenarioCaseAdapter {
  CaseScenarioSection: ComponentType<ScenarioCaseSectionProps>
  CaseCreateFields: ComponentType<ScenarioFormFieldsProps>
  buildCaseScenarioData: (values: ScenarioFormValues) => Record<string, unknown>
  caseMemberRoleOptions: readonly ScenarioCaseRoleOption[]
  // 活动在该 lifecycle 下可展示的命令；没有则返回空数组。
  caseCommands: (lifecycle: ReviewCaseLifecycle) => readonly ScenarioCaseCommand[]
}

export interface ScenarioCaseRoleOption {
  roleKey: string
  label: string
}

export interface ScenarioRelationshipOption {
  label: string
  actorKind: ActorKind
}

export interface ScenarioParticipantOption extends ScenarioRelationshipOption {
  roleKey: string
}

export interface ScenarioAssigneeOption extends ScenarioRelationshipOption {
  role: AssignmentRole
}

export interface ScenarioFindingCommandPorts {
  transition: (action: string, reason?: string) => Promise<unknown>
  submitRectification: (
    action: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown>
  submitVerification: (
    action: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown>
  reopen: (reason: string) => Promise<unknown>
}

export interface ScenarioCommandOptions {
  // 调用方能在表单字段上显示的服务端 422 字段名。
  fields?: readonly string[]
  // 页面是否同时显示失败提示；弹层自己显示失败时传 false。默认 true。
  notify?: boolean
}

export interface ScenarioFindingInteractionProps {
  finding: FindingResponse
  disabled?: boolean
  commands: ScenarioFindingCommandPorts
  execute: (
    label: string,
    command: () => Promise<unknown>,
    options?: ScenarioCommandOptions,
  ) => Promise<CommandResult>
}

export interface ScenarioFindingAdapter {
  // 该活动 lifecycle 下是否可以新建发现项（状态规则，不是权限）。
  canCreateFinding: (lifecycle: ReviewCaseLifecycle) => boolean
  // 概览里的场景字段（如问题类型、条款）。
  findingScenarioItems: (finding: FindingResponse) => readonly ScenarioDescriptionItem[]
  // 首屏展示的场景内分类（如观察项、不符合项）；没有则返回 null。
  findingKindLabel: (finding: FindingResponse) => string | null
  FindingCreateFields: ComponentType<ScenarioFormFieldsProps>
  buildFindingScenarioData: (values: ScenarioFormValues) => Record<string, unknown>
  participantOptions: readonly ScenarioParticipantOption[]
  assigneeOptions: readonly ScenarioAssigneeOption[]
  FindingInteractionSection: ComponentType<ScenarioFindingInteractionProps>
  // 按父级与整改项生命周期给出整改项写操作的前置条件。
  actionOperations: (context: ScenarioActionOperationContext) => ScenarioActionOperations
  // 按精确场景版本解释历史提交的 payload。
  describeSubmission: (submission: SubmissionResponse) => ScenarioSubmissionView
}

// 整改项页面已读取的确定生命周期；父级读取失败时为 null（未知）。
export interface ScenarioActionOperationContext {
  action: ActionItemLifecycle
  finding: FindingLifecycle | null
  reviewCase: ReviewCaseLifecycle | null
}

export interface ScenarioActionOperations {
  // 父级状态已确定不允许整改写操作时的解释；null 表示没有已确定的阻塞。
  blockedReason: string | null
  // 开始/完成/重开/取消/转交等命令是否还值得展示（仍须按整改项自身生命周期筛选）。
  writable: boolean
  manageAssignees: boolean
  uploadEvidence: boolean
}

export interface ScenarioUiAdapter extends ScenarioCaseAdapter, ScenarioFindingAdapter {}

export class ScenarioUiRegistry<T> {
  private readonly entries = new Map<string, T>()

  register(key: string, version: number, adapter: T): void {
    const identity = this.identity(key, version)
    if (this.entries.has(identity)) {
      throw new Error(`Scenario UI adapter already registered: ${identity}`)
    }
    this.entries.set(identity, adapter)
  }

  resolve(key: string, version: number): T | undefined {
    return this.entries.get(this.identity(key, version))
  }

  private identity(key: string, version: number): string {
    return `${key}\u0000${version}`
  }
}
