import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { createFinding } from '../../api/product'
import type { FindingSeverity, ReviewCaseResponse } from '../../api/product'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { resolveFindingScenarioAdapter } from '../../scenarios'
import type { ScenarioFormValues } from '../../scenarios/registry'
import { statusLabel } from '../../ui/StatusTag'

interface FindingCreatePanelProps {
  reviewCase: ReviewCaseResponse
}

export function FindingCreatePanel({ reviewCase }: FindingCreatePanelProps) {
  const navigate = useNavigate()
  const adapter = resolveFindingScenarioAdapter(
    reviewCase.scenario_key,
    reviewCase.scenario_version,
  )
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<FindingSeverity>('medium')
  const [scenarioValues, setScenarioValues] = useState<ScenarioFormValues>({})
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  if (adapter === undefined) {
    return (
      <section className="surface-card" aria-labelledby="create-finding-title">
        <h2 id="create-finding-title">新建发现项</h2>
        <p className="empty-note">
          当前审查场景的界面暂不支持创建发现项（{scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}）。
        </p>
      </section>
    )
  }

  const scenarioAdapter = adapter
  const ScenarioFields = scenarioAdapter.FindingCreateFields

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      const finding = await createFinding(reviewCase.id, {
        title,
        description: description.length > 0 ? description : null,
        severity,
        scenario_data: scenarioAdapter.buildFindingScenarioData(scenarioValues),
      })
      navigate(`/findings/${finding.id}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '发现项创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="surface-card" aria-labelledby="create-finding-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{scenarioName(reviewCase.scenario_key)}</p>
          <h2 id="create-finding-title">新建发现项</h2>
        </div>
      </div>
      <form className="command-form" onSubmit={(event) => void submit(event)}>
        <div className="form-grid">
          <label>
            标题
            <input value={title} onChange={(event) => setTitle(event.target.value)} disabled={submitting} />
          </label>
          <label>
            严重度
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as FindingSeverity)}
              disabled={submitting}
            >
              <option value="low">{statusLabel('severity', 'low')}</option>
              <option value="medium">{statusLabel('severity', 'medium')}</option>
              <option value="high">{statusLabel('severity', 'high')}</option>
              <option value="critical">{statusLabel('severity', 'critical')}</option>
            </select>
          </label>
        </div>
        <label>
          描述
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            disabled={submitting}
            rows={3}
          />
        </label>
        <ScenarioFields
          values={scenarioValues}
          onChange={(name, value) =>
            setScenarioValues((current) => ({ ...current, [name]: value }))
          }
          disabled={submitting}
        />
        {message === null ? null : <p role="alert">{message}</p>}
        <div className="command-row">
          <button type="submit" disabled={submitting}>{submitting ? '正在提交…' : '新建发现项'}</button>
          <span className="empty-note">服务器校验通过后才会保存发现项。</span>
        </div>
      </form>
    </section>
  )
}
