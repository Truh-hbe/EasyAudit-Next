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

function findingTypeText(value: unknown): string {
  if (value === 'nonconformity') return '不符合项'
  if (value === 'observation') return '观察项'
  return scenarioText(value)
}

function formValue(values: ScenarioFormValues, name: string): string {
  return values[name] ?? ''
}

export function ComplianceReviewV1CaseSection({ reviewCase }: ScenarioCaseSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="compliance-review-v1-title">
      <div className="section-heading">
        <div>
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

export function ComplianceReviewV1CaseCreateFields({
  values,
  onChange,
  disabled,
}: ScenarioFormFieldsProps) {
  return (
    <div className="form-grid">
      <label>
        标准 / 依据
        <input
          value={formValue(values, 'standard_reference')}
          onChange={(event) => onChange('standard_reference', event.target.value)}
          disabled={disabled}
        />
      </label>
      <label>
        范围摘要
        <input
          value={formValue(values, 'scope_summary')}
          onChange={(event) => onChange('scope_summary', event.target.value)}
          disabled={disabled}
        />
      </label>
    </div>
  )
}

export function ComplianceReviewV1FindingSection({ finding }: ScenarioFindingSectionProps) {
  return (
    <section className="surface-card" aria-labelledby="compliance-review-v1-finding-title">
      <div className="section-heading">
        <div>
          <h2 id="compliance-review-v1-finding-title">合规审查发现项信息</h2>
        </div>
      </div>
      <dl className="fact-grid">
        <div>
          <dt>条款 / 要求</dt>
          <dd>{scenarioText(finding.scenario_data.criterion_reference)}</dd>
        </div>
        <div>
          <dt>发现项类型</dt>
          <dd>{findingTypeText(finding.scenario_data.finding_type)}</dd>
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
        发现项类型
        <select
          value={formValue(values, 'finding_type')}
          onChange={(event) => onChange('finding_type', event.target.value)}
          disabled={disabled}
        >
          <option value="">请选择</option>
          <option value="nonconformity">不符合项</option>
          <option value="observation">观察项</option>
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
        以下操作按合规审查场景展示；最终授权、状态与并发判断以服务器为准。
      </p>
      {finding.lifecycle === 'open' && findingType === 'observation' ? (
        <div className="command-stack">
          <button
            type="button"
            data-scenario-action="accept_observation"
            onClick={() =>
              void execute('接受观察项', () => commands.transition('accept_observation'))
            }
            disabled={disabled}
          >
            接受观察项
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
              void execute('作废发现项', () => commands.transition('void', voidReason))
            }
            disabled={disabled}
          >
            作废发现项
          </button>
        </div>
      ) : null}
      {finding.lifecycle === 'open' &&
      findingType !== 'observation' &&
      findingType !== 'nonconformity' ? (
        <p role="status">当前发现项类型无法解释，业务操作已关闭。</p>
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
                placeholder="由服务器校验必填规则"
              />
            </label>
            <button type="submit" data-scenario-action="submit_plan" disabled={disabled}>
              提交整改计划
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
              通过验证
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
              驳回验证
            </button>
          </form>
        </div>
      ) : null}
      {finding.lifecycle === 'closed' && findingType === 'nonconformity' ? (
        <form
          className="command-form"
          onSubmit={(event) => {
            event.preventDefault()
            void execute('重新打开发现项', () => commands.reopen(reopenReason))
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
        <p className="empty-note">观察项已接受并闭环。</p>
      ) : null}
      {finding.lifecycle === 'voided' ? (
        <p className="empty-note">当前发现项已作废，没有可执行的操作。</p>
      ) : null}
    </section>
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
    { roleKey: 'owner', actorKind: 'user', label: '整改负责人' },
    { roleKey: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  assigneeOptions: [
    { role: 'primary', actorKind: 'user', label: '主要执行人' },
    { role: 'collaborator', actorKind: 'user', label: '协作者' },
  ],
  FindingInteractionSection: ComplianceReviewV1FindingInteraction,
}
