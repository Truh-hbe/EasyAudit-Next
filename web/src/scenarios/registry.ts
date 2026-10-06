import type { ComponentType } from 'react'

import type { CommandResult } from '../product/commandFailure'
import type {
  ActorKind,
  AssignmentRole,
  FindingResponse,
  ReviewCaseResponse,
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

export interface ScenarioFormFieldsProps {
  values: ScenarioFormValues
  onChange: (name: string, value: string) => void
  disabled?: boolean
  // 服务端 422 能对应到字段的提示，按字段名索引；只有已迁移到 antd 的表单会传入。
  fieldErrors?: Record<string, string>
}

export interface ScenarioCaseAdapter {
  CaseScenarioSection: ComponentType<ScenarioCaseSectionProps>
  CaseCreateFields: ComponentType<ScenarioFormFieldsProps>
  buildCaseScenarioData: (values: ScenarioFormValues) => Record<string, unknown>
  caseMemberRoleOptions: readonly ScenarioCaseRoleOption[]
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
  // 概览里的场景字段（如问题类型、条款）。
  findingScenarioItems: (finding: FindingResponse) => readonly ScenarioDescriptionItem[]
  // 首屏展示的场景内分类（如观察项、不符合项）；没有则返回 null。
  findingKindLabel: (finding: FindingResponse) => string | null
  FindingCreateFields: ComponentType<ScenarioFormFieldsProps>
  buildFindingScenarioData: (values: ScenarioFormValues) => Record<string, unknown>
  participantOptions: readonly ScenarioParticipantOption[]
  assigneeOptions: readonly ScenarioAssigneeOption[]
  FindingInteractionSection: ComponentType<ScenarioFindingInteractionProps>
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
