import { useState } from 'react'
import { useNavigate } from 'react-router'

import { createFinding } from '../../api/product'
import type { FindingSeverity, ReviewCaseResponse } from '../../api/product'
import { resolveFindingScenarioAdapter } from '../../scenarios'
import type { ScenarioFormValues } from '../../scenarios/registry'

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
        <h2 id="create-finding-title">新建 Finding</h2>
        <p className="empty-note">
          当前精确 Scenario UI 不支持创建：{reviewCase.scenario_key}@{reviewCase.scenario_version}。
        </p>
      </section>
    )
  }

  const ScenarioFields = adapter.FindingCreateFields

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      const finding = await createFinding(reviewCase.id, {
        title,
        description: description.length > 0 ? description : null,
        severity,
        scenario_data: adapter.buildFindingScenarioData(scenarioValues),
      })
      navigate(`/findings/${finding.id}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Finding 创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="surface-card" aria-labelledby="create-finding-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{reviewCase.scenario_key}@{reviewCase.scenario_version}</p>
          <h2 id="create-finding-title">新建 Finding</h2>
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
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
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
          <button type="submit" disabled={submitting}>{submitting ? '正在提交…' : '创建 Finding'}</button>
          <span className="empty-note">服务器验证成功后才会产生持久 Finding。</span>
        </div>
      </form>
    </section>
  )
}
