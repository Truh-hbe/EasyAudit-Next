import { useState } from 'react'

import type {
  ScenarioCaseSectionProps,
  ScenarioFindingInteractionProps,
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

export function ProcessReviewV1CaseCreateFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <div className="form-grid">
      <label>
        区域代码
        <input
          value={formValue(values, 'area_code')}
          onChange={(event) => onChange('area_code', event.target.value)}
          disabled={disabled}
        />
      </label>
      <label>
        审查类型
        <input
          value={formValue(values, 'review_type')}
          onChange={(event) => onChange('review_type', event.target.value)}
          disabled={disabled}
        />
      </label>
    </div>
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

export function ProcessReviewV1FindingInteraction({
  finding,
  disabled,
  commands,
  execute,
}: ScenarioFindingInteractionProps) {
  const [voidReason, setVoidReason] = useState('')
  const [rootCause, setRootCause] = useState('')
  const [completionComment, setCompletionComment] = useState('')
  const [verificationComment, setVerificationComment] = useState('')
  const [reopenReason, setReopenReason] = useState('')

  return (
    <section className="surface-card" aria-labelledby="finding-command-title">
      <h2 id="finding-command-title">业务操作</h2>
      <p className="empty-note">
        当前操作由 process_review@1 adapter 展示；最终授权、生命周期与并发判断仍由服务器决定。
      </p>
      {finding.lifecycle === 'open' ? (
        <div className="command-stack">
          <button
            type="button"
            data-scenario-action="issue"
            onClick={() => void execute('签发 Finding', () => commands.transition('issue'))}
            disabled={disabled}
          >
            签发 Finding
          </button>
          <label>
            作废原因
            <input
              value={voidReason}
              onChange={(event) => setVoidReason(event.target.value)}
              disabled={disabled}
            />
          </label>
          <button
            type="button"
            className="secondary"
            data-scenario-action="void"
            onClick={() =>
              void execute('作废 Finding', () => commands.transition('void', voidReason))
            }
            disabled={disabled}
          >
            作废 Finding
          </button>
        </div>
      ) : null}
      {finding.lifecycle === 'rectifying' ? (
        <div className="command-grid">
          <form
            className="command-form subsurface"
            onSubmit={(event) => {
              event.preventDefault()
              void execute('提交整改计划', () =>
                commands.submitRectification('submit_plan', {
                  stage: 'plan',
                  root_cause: rootCause,
                }),
              )
            }}
          >
            <h3>整改计划</h3>
            <label>
              根本原因
              <input
                value={rootCause}
                onChange={(event) => setRootCause(event.target.value)}
                disabled={disabled}
                placeholder="由后端验证必填规则"
              />
            </label>
            <button type="submit" data-scenario-action="submit_plan" disabled={disabled}>
              提交正式计划
            </button>
          </form>
          <form
            className="command-form subsurface"
            onSubmit={(event) => {
              event.preventDefault()
              void execute('提交验证', () =>
                commands.submitRectification('submit_for_verification', {
                  stage: 'completion',
                  comment: completionComment,
                }),
              )
            }}
          >
            <h3>整改完成</h3>
            <label>
              整改完成说明
              <input
                value={completionComment}
                onChange={(event) => setCompletionComment(event.target.value)}
                disabled={disabled}
                placeholder="后端将验证 Action 完成状态与说明"
              />
            </label>
            <button
              type="submit"
              data-scenario-action="submit_for_verification"
              disabled={disabled}
            >
              提交验证
            </button>
          </form>
        </div>
      ) : null}
      {finding.lifecycle === 'verifying' ? (
        <div className="command-grid">
          <div className="subsurface">
            <h3>验证通过</h3>
            <button
              type="button"
              data-scenario-action="approve"
              onClick={() =>
                void execute('验证通过', () =>
                  commands.submitVerification('approve', { result: 'approved' }),
                )
              }
              disabled={disabled}
            >
              Approve
            </button>
          </div>
          <form
            className="command-form subsurface"
            onSubmit={(event) => {
              event.preventDefault()
              void execute('验证驳回', () =>
                commands.submitVerification('reject', {
                  result: 'rejected',
                  comment: verificationComment,
                }),
              )
            }}
          >
            <h3>验证驳回</h3>
            <label>
              驳回原因
              <input
                value={verificationComment}
                onChange={(event) => setVerificationComment(event.target.value)}
                disabled={disabled}
                placeholder="驳回时由后端验证必填规则"
              />
            </label>
            <button
              type="submit"
              className="secondary"
              data-scenario-action="reject"
              disabled={disabled}
            >
              Reject
            </button>
          </form>
        </div>
      ) : null}
      {finding.lifecycle === 'closed' ? (
        <form
          className="command-form"
          onSubmit={(event) => {
            event.preventDefault()
            void execute('重新打开 Finding', () => commands.reopen(reopenReason))
          }}
        >
          <label>
            重新打开原因
            <input
              value={reopenReason}
              onChange={(event) => setReopenReason(event.target.value)}
              disabled={disabled}
            />
          </label>
          <button type="submit" data-scenario-action="reopen" disabled={disabled}>
            重新打开
          </button>
        </form>
      ) : null}
      {finding.lifecycle === 'voided' ? (
        <p className="empty-note">当前 Finding 已作废，无可用 Product mutation。</p>
      ) : null}
    </section>
  )
}

export const PROCESS_REVIEW_V1_UI: ScenarioUiAdapter = {
  CaseScenarioSection: ProcessReviewV1CaseSection,
  CaseCreateFields: ProcessReviewV1CaseCreateFields,
  buildCaseScenarioData: (values) => ({
    area_code: formValue(values, 'area_code'),
    review_type: formValue(values, 'review_type'),
  }),
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
  FindingInteractionSection: ProcessReviewV1FindingInteraction,
}
