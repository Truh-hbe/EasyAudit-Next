import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { createReviewPlan, getReviewCatalog } from '../../api/product'
import type { ReviewCatalogItemResponse } from '../../api/product'
import { resolveCaseScenarioAdapter } from '../../scenarios'

type CatalogState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: ReviewCatalogItemResponse[] }

export function dateInputToApi(value: string): string | null {
  if (value.trim() === '') return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function ReviewPlanCreatePage() {
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'loading' })
  const [title, setTitle] = useState('')
  const [plannedStartAt, setPlannedStartAt] = useState('')
  const [plannedEndAt, setPlannedEndAt] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void getReviewCatalog(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setCatalog({ status: 'ready', items })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setCatalog({ status: 'error', message: errorMessage(error, '审查场景目录读取失败') })
      })
    return () => controller.abort()
  }, [])

  async function submitPlan(): Promise<void> {
    if (submitting) return
    if (title.trim() === '') {
      setSubmitError('请输入审查计划名称。')
      return
    }
    if (title !== title.trim()) {
      setSubmitError('审查计划名称前后不能有空格。')
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    try {
      const plan = await createReviewPlan({
        title,
        planned_start_at: dateInputToApi(plannedStartAt),
        planned_end_at: dateInputToApi(plannedEndAt),
      })
      await navigate(`/review-plans/${encodeURIComponent(plan.id)}/review-cases/new`)
    } catch (error: unknown) {
      setSubmitError(errorMessage(error, '审查计划创建失败，请稍后重试。'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="surface-page" aria-labelledby="review-plan-create-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">M5.2 · step 1 of 2</p>
          <h1 id="review-plan-create-title">新建审查计划</h1>
        </div>
        <span className="wizard-step">先保存计划，再创建案例</span>
      </div>

      <div className="surface-card">
        <h2>计划信息</h2>
        <p className="field-help">计划保存成功后，下一步会使用地址中的计划编号继续。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void submitPlan()
          }}
        >
          <label>
            计划名称
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              maxLength={300}
              disabled={submitting}
              autoComplete="off"
            />
          </label>
          <div className="form-grid">
            <label>
              计划开始时间（可选）
              <input
                type="datetime-local"
                value={plannedStartAt}
                onChange={(event) => setPlannedStartAt(event.target.value)}
                disabled={submitting}
              />
            </label>
            <label>
              计划结束时间（可选）
              <input
                type="datetime-local"
                value={plannedEndAt}
                onChange={(event) => setPlannedEndAt(event.target.value)}
                disabled={submitting}
              />
            </label>
          </div>
          {catalog.status === 'loading' ? <p role="status">正在读取可用审查场景…</p> : null}
          {catalog.status === 'error' ? <p role="alert">{catalog.message}</p> : null}
          {catalog.status === 'ready' && catalog.items.length === 0 ? (
            <p role="alert">当前没有可创建的已发布审查场景。</p>
          ) : null}
          {submitError === null ? null : <p role="alert">{submitError}</p>}
          <div className="wizard-actions">
            <button
              type="submit"
              disabled={submitting || catalog.status !== 'ready' || catalog.items.length === 0}
            >
              {submitting ? '正在保存计划…' : '保存计划并继续'}
            </button>
          </div>
        </form>
      </div>

      {catalog.status === 'ready' ? (
        <div className="surface-card" aria-label="可用审查场景">
          <h2>本次可创建的场景</h2>
          <ul className="surface-list">
            {catalog.items.map((item) => {
              const supported = resolveCaseScenarioAdapter(item.scenario_key, item.scenario_version)
              return (
                <li key={`${item.scenario_key}@${item.scenario_version}`}>
                  <strong>{item.display_name}</strong>
                  <span>{item.scenario_key}@{item.scenario_version}</span>
                  <span>{supported === undefined ? '当前页面暂不支持' : '可在下一步选择'}</span>
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
