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
import { FindingCreateTextField } from './FindingCreateFields'
import {
  CommandNote,
  CommandRow,
  DirectCommand,
  FindingCommandCard,
  RectificationCommands,
  ReopenCommand,
  VerificationCommands,
  VoidCommand,
} from './findingCommandKit'
import { standardCanCreateFinding, standardCaseCommands } from './caseCommandKit'
import { standardDescribeSubmission } from './submissionKit'
import { ScenarioFieldsCard } from './ScenarioFieldsCard'

function scenarioText(value: unknown): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : '—'
}

function formValue(values: ScenarioFormValues, name: string): string {
  return values[name] ?? ''
}

function caseItems(reviewCase: ReviewCaseResponse): ScenarioDescriptionItem[] {
  return [
    { key: 'area_code', label: '区域代码', value: scenarioText(reviewCase.scenario_data.area_code) },
    { key: 'review_type', label: '审查类型', value: scenarioText(reviewCase.scenario_data.review_type) },
  ]
}

export function ProcessReviewV1CaseSection({ reviewCase }: ScenarioCaseSectionProps) {
  return <ScenarioFieldsCard id="process-review-v1-title" title="过程审查信息" items={caseItems(reviewCase)} />
}

export function ProcessReviewV1CaseCreateFields({
  values,
  onChange,
  disabled,
  fieldErrors,
}: ScenarioFormFieldsProps) {
  return (
    <>
      <CaseCreateTextField
        name="area_code"
        label="区域代码"
        value={formValue(values, 'area_code')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.area_code}
      />
      <CaseCreateTextField
        name="review_type"
        label="审查类型"
        value={formValue(values, 'review_type')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.review_type}
      />
    </>
  )
}

function findingItems(finding: FindingResponse): ScenarioDescriptionItem[] {
  return [
    { key: 'issue_type', label: '问题类型', value: scenarioText(finding.scenario_data.issue_type) },
    { key: 'project_category', label: '项目类别', value: scenarioText(finding.scenario_data.project_category) },
  ]
}

export function ProcessReviewV1FindingCreateFields({
  values,
  onChange,
  disabled,
  fieldErrors,
}: ScenarioFormFieldsProps) {
  return (
    <>
      <FindingCreateTextField
        name="issue_type"
        label="问题类型"
        placeholder="由审查场景校验"
        value={formValue(values, 'issue_type')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.issue_type}
      />
      <FindingCreateTextField
        name="project_category"
        label="项目类别"
        placeholder="由审查场景校验"
        value={formValue(values, 'project_category')}
        onChange={onChange}
        disabled={disabled}
        error={fieldErrors?.project_category}
      />
    </>
  )
}

export function ProcessReviewV1FindingInteraction(props: ScenarioFindingInteractionProps) {
  const { finding, commands, execute, disabled } = props
  const shared = { commands, execute, disabled }
  return (
    <FindingCommandCard scenarioLabel="过程审查">
      <CommandRow>
        {finding.lifecycle === 'open' ? (
          <>
            <DirectCommand
              primary
              execute={execute}
              disabled={disabled}
              action="issue"
              label="签发发现项"
              buttonText="签发发现项"
              run={() => commands.transition('issue')}
            />
            <VoidCommand {...shared} />
          </>
        ) : null}
        {finding.lifecycle === 'rectifying' ? <RectificationCommands {...shared} /> : null}
        {finding.lifecycle === 'verifying' ? <VerificationCommands {...shared} /> : null}
        {finding.lifecycle === 'closed' ? <ReopenCommand {...shared} /> : null}
      </CommandRow>
      {finding.lifecycle === 'voided' ? <CommandNote>当前发现项已作废，没有可执行的操作。</CommandNote> : null}
    </FindingCommandCard>
  )
}

export const PROCESS_REVIEW_V1_UI: ScenarioUiAdapter = {
  CaseScenarioSection: ProcessReviewV1CaseSection,
  CaseCreateFields: ProcessReviewV1CaseCreateFields,
  buildCaseScenarioData: (values) => ({
    area_code: formValue(values, 'area_code'),
    review_type: formValue(values, 'review_type'),
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
  findingKindLabel: () => null,
  FindingCreateFields: ProcessReviewV1FindingCreateFields,
  buildFindingScenarioData: (values) => ({
    issue_type: formValue(values, 'issue_type'),
    project_category: formValue(values, 'project_category'),
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
  FindingInteractionSection: ProcessReviewV1FindingInteraction,
  describeSubmission: standardDescribeSubmission,
}
