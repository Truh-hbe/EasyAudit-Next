import type {
  ScenarioCaseSectionProps,
  ScenarioFindingSectionProps,
  ScenarioFormFieldsProps,
  ScenarioFormValues,
  ScenarioUiAdapter,
} from './registry'

function scenarioText(value: unknown): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : '—'
}

function formValue(values: ScenarioFormValues, name: string): string {
  return values[name] ?? ''
}

export function ProcessReviewV1CaseSection({ reviewCase }: ScenarioCaseSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="process-review-v1-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">process_review@1</p>
          <h2 id="process-review-v1-title">过程审查信息</h2>
        </div>
      </div>
      <dl className="fact-grid">
        <div>
          <dt>区域代码</dt>
          <dd>{scenarioText(reviewCase.scenario_data.area_code)}</dd>
        </div>
        <div>
          <dt>审查类型</dt>
          <dd>{scenarioText(reviewCase.scenario_data.review_type)}</dd>
        </div>
      </dl>
    </section>
  )
}

export function ProcessReviewV1FindingSection({ finding }: ScenarioFindingSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="process-review-v1-finding-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">process_review@1</p>
          <h2 id="process-review-v1-finding-title">过程审查 Finding 信息</h2>
        </div>
      </div>
      <dl className="fact-grid">
        <div>
          <dt>问题类型</dt>
          <dd>{scenarioText(finding.scenario_data.issue_type)}</dd>
        </div>
        <div>
          <dt>项目类别</dt>
          <dd>{scenarioText(finding.scenario_data.project_category)}</dd>
        </div>
      </dl>
    </section>
  )
}

export function ProcessReviewV1FindingCreateFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <div className="form-grid">
      <label>
        问题类型
        <input
          value={formValue(values, 'issue_type')}
          onChange={(event) => onChange('issue_type', event.target.value)}
          disabled={disabled}
          placeholder="由 Scenario 校验"
        />
      </label>
      <label>
        项目类别
        <input
          value={formValue(values, 'project_category')}
          onChange={(event) => onChange('project_category', event.target.value)}
          disabled={disabled}
          placeholder="由 Scenario 校验"
        />
      </label>
    </div>
  )
}

export function ProcessReviewV1RectificationPlanFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <label>
      根本原因
      <input
        value={formValue(values, 'root_cause')}
        onChange={(event) => onChange('root_cause', event.target.value)}
        disabled={disabled}
        placeholder="由后端验证必填规则"
      />
    </label>
  )
}

export function ProcessReviewV1CompletionFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <label>
      整改完成说明
      <input
        value={formValue(values, 'completion_comment')}
        onChange={(event) => onChange('completion_comment', event.target.value)}
        disabled={disabled}
        placeholder="后端将验证 Action 完成状态与说明"
      />
    </label>
  )
}

export function ProcessReviewV1VerificationRejectFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <label>
      驳回原因
      <input
        value={formValue(values, 'verification_comment')}
        onChange={(event) => onChange('verification_comment', event.target.value)}
        disabled={disabled}
        placeholder="驳回时由后端验证必填规则"
      />
    </label>
  )
}

export const PROCESS_REVIEW_V1_UI: ScenarioUiAdapter = {
  CaseScenarioSection: ProcessReviewV1CaseSection,
  FindingScenarioSection: ProcessReviewV1FindingSection,
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
    { roleKey: 'owner', actorKind: 'user', label: '负责人' },
    { roleKey: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  assigneeOptions: [
    { role: 'primary', actorKind: 'user', label: '主要执行人' },
    { role: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  RectificationPlanFields: ProcessReviewV1RectificationPlanFields,
  buildRectificationPlanPayload: (values) => ({
    stage: 'plan',
    root_cause: formValue(values, 'root_cause'),
  }),
  CompletionFields: ProcessReviewV1CompletionFields,
  buildCompletionPayload: (values) => ({
    stage: 'completion',
    comment: formValue(values, 'completion_comment'),
  }),
  VerificationRejectFields: ProcessReviewV1VerificationRejectFields,
  buildVerificationPayload: (action, values) =>
    action === 'approve'
      ? { result: 'approved' }
      : {
          result: 'rejected',
          comment: formValue(values, 'verification_comment'),
        },
}
