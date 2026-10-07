import type {
  ScenarioCaseSectionProps,
  ScenarioDescriptionItem,
  ScenarioFindingInteractionProps,
  ScenarioFormFieldsProps,
  ScenarioFormValues,
  ScenarioUiAdapter,
} from './registry'
import type { FindingResponse, ReviewCaseResponse } from '../api/product'
import { CaseCreateTextField } from './CaseCreateTextField'
import { FindingCreateRadioField, FindingCreateTextField } from './FindingCreateFields'
import {
  CommandNote,
  CommandRow,
  ConfirmedCommand,
  DirectCommand,
  FindingCommandCard,
  RectificationCommands,
  ReopenCommand,
  VerificationCommands,
  VoidCommand,
} from './findingCommandKit'
import { standardCanCreateFinding, standardCaseCommands } from './caseCommandKit'
import { ScenarioFieldsCard } from './ScenarioFieldsCard'

function scenarioText(value: unknown): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : '—'
}

function findingTypeText(value: unknown): string {
  if (value === 'nonconformity') return '不符合项'
  if (value === 'observation') return '观察项'
  return scenarioText(value)
}

function formValue(values: ScenarioFormValues, name: string): string {
  return values[name] ?? ''
}

function caseItems(reviewCase: ReviewCaseResponse): ScenarioDescriptionItem[] {
  return [
    { key: 'standard_reference', label: '标准 / 依据', value: scenarioText(reviewCase.scenario_data.standard_reference) },
    { key: 'scope_summary', label: '范围摘要', value: scenarioText(reviewCase.scenario_data.scope_summary) },
  ]
}

export function ComplianceReviewV1CaseSection({ reviewCase }: ScenarioCaseSectionProps) {
  return <ScenarioFieldsCard id="compliance-review-v1-title" title="合规审查信息" items={caseItems(reviewCase)} />
}

export function ComplianceReviewV1CaseCreateFields({
  values,
  onChange,
  disabled,
  fieldErrors,
}: ScenarioFormFieldsProps) {
  return (
    <>
      <CaseCreateTextField
        name="standard_reference"
        label="标准 / 依据"
        value={formValue(values, 'standard_reference')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.standard_reference}
      />
      <CaseCreateTextField
        name="scope_summary"
        label="范围摘要"
        value={formValue(values, 'scope_summary')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.scope_summary}
      />
    </>
  )
}

function findingItems(finding: FindingResponse): ScenarioDescriptionItem[] {
  return [
    { key: 'criterion_reference', label: '条款 / 要求', value: scenarioText(finding.scenario_data.criterion_reference) },
    { key: 'finding_type', label: '发现项类型', value: findingTypeText(finding.scenario_data.finding_type) },
  ]
}

export function ComplianceReviewV1FindingCreateFields({
  values,
  onChange,
  disabled,
  fieldErrors,
}: ScenarioFormFieldsProps) {
  return (
    <>
      <FindingCreateTextField
        name="criterion_reference"
        label="条款 / 要求"
        placeholder="例如 8.5.1"
        value={formValue(values, 'criterion_reference')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.criterion_reference}
      />
      <FindingCreateRadioField
        name="finding_type"
        label="发现项类型"
        value={formValue(values, 'finding_type')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.finding_type}
        options={[
          { value: 'nonconformity', label: '不符合项' },
          { value: 'observation', label: '观察项' },
        ]}
      />
    </>
  )
}

export function ComplianceReviewV1FindingInteraction(props: ScenarioFindingInteractionProps) {
  const { finding, commands, execute, disabled } = props
  const shared = { commands, execute, disabled }
  const findingType = finding.scenario_data.finding_type
  const interpretable = findingType === 'observation' || findingType === 'nonconformity'
  return (
    <FindingCommandCard scenarioLabel="合规审查">
      <CommandRow>
        {finding.lifecycle === 'open' && findingType === 'observation' ? (
          <ConfirmedCommand
            primary
            execute={execute}
            commands={commands}
            disabled={disabled}
            action="accept_observation"
            label="接受观察项"
            buttonText="接受观察项"
            confirmTitle="接受观察项"
            confirmContent="接受后观察项直接关闭，不需要整改项。"
            confirmOkText="确认接受并关闭"
            run={() => commands.transition('accept_observation')}
          />
        ) : null}
        {finding.lifecycle === 'open' && findingType === 'nonconformity' ? (
          <DirectCommand
            primary
            execute={execute}
            disabled={disabled}
            action="issue"
            label="签发不符合项"
            buttonText="签发不符合项"
            run={() => commands.transition('issue')}
          />
        ) : null}
        {finding.lifecycle === 'open' && interpretable ? <VoidCommand {...shared} /> : null}
        {finding.lifecycle === 'rectifying' ? <RectificationCommands {...shared} /> : null}
        {finding.lifecycle === 'verifying' ? <VerificationCommands {...shared} /> : null}
        {finding.lifecycle === 'closed' && findingType === 'nonconformity' ? <ReopenCommand {...shared} /> : null}
        {finding.lifecycle === 'closed' && findingType === 'observation' ? (
          <ReopenCommand {...shared} description="重新打开后观察项回到待处理，可再次接受，请说明原因。" />
        ) : null}
      </CommandRow>
      {finding.lifecycle === 'open' && !interpretable ? (
        <CommandNote>当前发现项类型无法解释，业务操作已关闭。</CommandNote>
      ) : null}
      {finding.lifecycle === 'closed' && findingType === 'observation' ? (
        <CommandNote>观察项已接受并闭环。</CommandNote>
      ) : null}
      {finding.lifecycle === 'voided' ? <CommandNote>当前发现项已作废，没有可执行的操作。</CommandNote> : null}
    </FindingCommandCard>
  )
}

export const COMPLIANCE_REVIEW_V1_UI: ScenarioUiAdapter = {
  CaseScenarioSection: ComplianceReviewV1CaseSection,
  CaseCreateFields: ComplianceReviewV1CaseCreateFields,
  buildCaseScenarioData: (values) => ({
    standard_reference: formValue(values, 'standard_reference'),
    scope_summary: formValue(values, 'scope_summary'),
  }),
  caseMemberRoleOptions: [
    { roleKey: 'lead', label: '审查组长' },
    { roleKey: 'auditor', label: '审查员' },
    { roleKey: 'reviewer', label: '复核员' },
    { roleKey: 'observer', label: '观察员' },
  ],
  caseCommands: standardCaseCommands,
  canCreateFinding: standardCanCreateFinding,
  findingScenarioItems: findingItems,
  findingKindLabel: (finding) => {
    const label = findingTypeText(finding.scenario_data.finding_type)
    return label === '—' ? null : label
  },
  FindingCreateFields: ComplianceReviewV1FindingCreateFields,
  buildFindingScenarioData: (values) => ({
    criterion_reference: formValue(values, 'criterion_reference'),
    finding_type: formValue(values, 'finding_type'),
  }),
  participantOptions: [
    {
      roleKey: 'responsible_department',
      actorKind: 'department',
      label: '责任部门',
    },
    { roleKey: 'owner', actorKind: 'user', label: '整改负责人' },
    { roleKey: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  assigneeOptions: [
    { role: 'primary', actorKind: 'user', label: '主要执行人' },
    { role: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  FindingInteractionSection: ComplianceReviewV1FindingInteraction,
}
