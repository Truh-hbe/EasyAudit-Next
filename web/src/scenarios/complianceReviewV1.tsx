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

export function ComplianceReviewV1CaseSection({ reviewCase }: ScenarioCaseSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="compliance-review-v1-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">compliance_review@1</p>
          <h2 id="compliance-review-v1-title">合规审查信息</h2>
        </div>
      </div>
      <dl className="fact-grid">
        <div>
          <dt>标准 / 依据</dt>
          <dd>{scenarioText(reviewCase.scenario_data.standard_reference)}</dd>
        </div>
        <div>
          <dt>范围摘要</dt>
          <dd>{scenarioText(reviewCase.scenario_data.scope_summary)}</dd>
        </div>
      </dl>
    </section>
  )
}

export function ComplianceReviewV1FindingSection({ finding }: ScenarioFindingSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="compliance-review-v1-finding-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">compliance_review@1</p>
          <h2 id="compliance-review-v1-finding-title">合规 Finding 信息</h2>
        </div>
      </div>
      <dl className="fact-grid">
        <div>
          <dt>条款 / 要求</dt>
          <dd>{scenarioText(finding.scenario_data.criterion_reference)}</dd>
        </div>
        <div>
          <dt>Finding 类型</dt>
          <dd>{scenarioText(finding.scenario_data.finding_type)}</dd>
        </div>
      </dl>
    </section>
  )
}

export function ComplianceReviewV1FindingCreateFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <div className="form-grid">
      <label>
        条款 / 要求
        <input
          value={formValue(values, 'criterion_reference')}
          onChange={(event) => onChange('criterion_reference', event.target.value)}
          disabled={disabled}
          placeholder="例如 8.5.1"
        />
      </label>
      <label>
        Finding 类型
        <select
          value={formValue(values, 'finding_type')}
          onChange={(event) => onChange('finding_type', event.target.value)}
          disabled={disabled}
        >
          <option value="">请选择</option>
          <option value="nonconformity">Nonconformity</option>
          <option value="observation">Observation</option>
        </select>
      </label>
    </div>
  )
}

export function ComplianceReviewV1FindingInteraction({
  finding,
  disabled,
  commands,
  execute,
}: ScenarioFindingInteractionProps) {
  const findingType = finding.scenario_data.finding_type
  const [voidReason, setVoidReason] = useState('')
  const [rootCause, setRootCause] = useState('')
  const [completionComment, setCompletionComment] = useState('')
  const [verificationComment, setVerificationComment] = useState('')
  const [reopenReason, setReopenReason] = useState('')

  return (
    <section className="surface-card" aria-labelledby="finding-command-title">
      <h2 id="finding-command-title">业务操作</h2>
      <p className="empty-note">
        当前操作由 compliance_review@1 adapter 展示；最终授权、生命周期与并发判断仍由服务器决定。
      </p>
      {finding.lifecycle === 'open' && findingType === 'observation' ? (
        <div className="command-stack">
          <button
            type="button"
            data-scenario-action="accept_observation"
            onClick={() =>
              void execute('接受 Observation', () => commands.transition('accept_observation'))
            }
            disabled={disabled}
          >
            接受 Observation
          </button>
        </div>
      ) : null}
      {finding.lifecycle === 'open' && findingType === 'nonconformity' ? (
        <div className="command-stack">
          <button
            type="button"
            data-scenario-action="issue"
            onClick={() => void execute('签发不符合项', () => commands.transition('issue'))}
            disabled={disabled}
          >
            签发不符合项
          </button>
        </div>
      ) : null}
      {finding.lifecycle === 'open' &&
      (findingType === 'observation' || findingType === 'nonconformity') ? (
        <div className="command-stack">
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
      {finding.lifecycle === 'open' &&
      findingType !== 'observation' &&
      findingType !== 'nonconformity' ? (
        <p role="status">当前 Finding 类型无法由 compliance_review@1 解释，业务操作已关闭。</p>
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
      {finding.lifecycle === 'closed' && findingType === 'nonconformity' ? (
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
      {finding.lifecycle === 'closed' && findingType === 'observation' ? (
        <p className="empty-note">Observation 已接受并闭环。</p>
      ) : null}
      {finding.lifecycle === 'voided' ? (
        <p className="empty-note">当前 Finding 已作废，无可用 Product mutation。</p>
      ) : null}
    </section>
  )
}

export const COMPLIANCE_REVIEW_V1_UI: ScenarioUiAdapter = {
  CaseScenarioSection: ComplianceReviewV1CaseSection,
  FindingScenarioSection: ComplianceReviewV1FindingSection,
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
    { roleKey: 'owner', actorKind: 'user', label: '负责人' },
    { roleKey: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  assigneeOptions: [
    { role: 'primary', actorKind: 'user', label: '主要执行人' },
    { role: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  FindingInteractionSection: ComplianceReviewV1FindingInteraction,
}
