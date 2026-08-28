import type { ComponentType } from 'react'

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

export interface ScenarioFindingSectionProps {
  finding: FindingResponse
}

export interface ScenarioFormFieldsProps {
  values: ScenarioFormValues
  onChange: (name: string, value: string) => void
  disabled?: boolean
}

export interface ScenarioCaseAdapter {
  CaseScenarioSection: ComponentType<ScenarioCaseSectionProps>
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

export interface ScenarioFindingAdapter {
  FindingScenarioSection: ComponentType<ScenarioFindingSectionProps>
  FindingCreateFields: ComponentType<ScenarioFormFieldsProps>
  buildFindingScenarioData: (values: ScenarioFormValues) => Record<string, unknown>
  participantOptions: readonly ScenarioParticipantOption[]
  assigneeOptions: readonly ScenarioAssigneeOption[]
  RectificationPlanFields: ComponentType<ScenarioFormFieldsProps>
  buildRectificationPlanPayload: (values: ScenarioFormValues) => Record<string, unknown>
  CompletionFields: ComponentType<ScenarioFormFieldsProps>
  buildCompletionPayload: (values: ScenarioFormValues) => Record<string, unknown>
  VerificationRejectFields: ComponentType<ScenarioFormFieldsProps>
  buildVerificationPayload: (
    action: 'approve' | 'reject',
    values: ScenarioFormValues,
  ) => Record<string, unknown>
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
