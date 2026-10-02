import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { ApiError, isIdempotencyKeyReuse } from '../../api/client'
import { createReviewPlan, getReviewCatalog, newIdempotencyKey } from '../../api/product'
import type { ReviewCatalogItemResponse, ReviewPlanResponse } from '../../api/product'
import {
  DISPLAY_TIME_ZONE_HINT,
  invalidDisplayZoneInputMessage,
  parseOptionalDisplayZoneInput,
} from '../../product/format'
import { resolveCaseScenarioAdapter } from '../../scenarios'

type CatalogState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: ReviewCatalogItemResponse[] }

export type PlanSubmitState =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'rejected'; message: string }
  | { status: 'unknown'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function isDefinitivePlanRejection(error: unknown): boolean {
  return error instanceof ApiError
}

// An unknown outcome may be retried by hand: the retry reuses the form's Idempotency-Key, so the
// server either creates the plan once or replays the first result. It is never retried automatically.
export function canSubmitPlan(state: PlanSubmitState): boolean {
  return state.status !== 'submitting'
}

function planRejectionMessage(error: unknown): string {
  if (isIdempotencyKeyReuse(error)) {
    return '当前内容与之前提交的创建请求不一致。请刷新页面，确认内容后再试。'
  }
  return errorMessage(error, '审查计划创建被服务器拒绝，请修正后重试。')
}

export async function executePlanSubmission(
  request: () => Promise<ReviewPlanResponse>,
): Promise<{ state: PlanSubmitState; plan?: ReviewPlanResponse }> {
  try {
    return { state: { status: 'idle' }, plan: await request() }
  } catch (error: unknown) {
    return {
      state: isDefinitivePlanRejection(error)
        ? { status: 'rejected', message: planRejectionMessage(error) }
        : {
            status: 'unknown',
            message: '审查计划创建结果未知。可以重试保存：重新提交会沿用这次创建请求，不会重复创建；系统不会自动再次提交。',
          },
    }
  }
}

export function ReviewPlanCreatePage() {
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'loading' })
  const [title, setTitle] = useState('')
  const [plannedStartAt, setPlannedStartAt] = useState('')
  const [plannedEndAt, setPlannedEndAt] = useState('')
  const [submitState, setSubmitState] = useState<PlanSubmitState>({ status: 'idle' })
  const submitting = submitState.status === 'submitting'
  // One key per form lifetime: retries, double clicks and resubmits after a network failure share it.
  const idempotencyKey = useRef(newIdempotencyKey())

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
    if (!canSubmitPlan(submitState)) return
    if (title.trim() === '') {
      setSubmitState({ status: 'rejected', message: '请输入审查计划名称。' })
      return
    }
    if (title !== title.trim()) {
      setSubmitState({ status: 'rejected', message: '审查计划名称前后不能有空格。' })
      return
    }

    // 无效时间不能当作"未填写"提交；保留输入和幂等键，由用户修改后重试。
    const startAt = parseOptionalDisplayZoneInput(plannedStartAt)
    if (!startAt.valid) {
      setSubmitState({ status: 'rejected', message: invalidDisplayZoneInputMessage('计划开始时间') })
      return
    }
    const endAt = parseOptionalDisplayZoneInput(plannedEndAt)
    if (!endAt.valid) {
      setSubmitState({ status: 'rejected', message: invalidDisplayZoneInputMessage('计划结束时间') })
      return
    }

    setSubmitState({ status: 'submitting' })
    const result = await executePlanSubmission(() => createReviewPlan({
        title,
        planned_start_at: startAt.iso,
        planned_end_at: endAt.iso,
      }, idempotencyKey.current))
    if (result.plan !== undefined) {
      idempotencyKey.current = newIdempotencyKey()
      await navigate(`/review-plans/${encodeURIComponent(result.plan.id)}/review-cases/new`)
    } else {
      setSubmitState(result.state)
    }
  }

  return (
    <section className="surface-page" aria-labelledby="review-plan-create-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">第 1 步，共 2 步</p>
          <h1 id="review-plan-create-title">新建审查计划</h1>
        </div>
        <span className="wizard-step">先保存计划，再创建审查活动</span>
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
          <p id="plan-time-zone-hint" className="field-help">{DISPLAY_TIME_ZONE_HINT}</p>
          <div className="form-grid">
            <label>
              计划开始时间（可选）
              <input
                type="datetime-local"
                aria-describedby="plan-time-zone-hint"
                value={plannedStartAt}
                onChange={(event) => setPlannedStartAt(event.target.value)}
                disabled={submitting}
              />
            </label>
            <label>
              计划结束时间（可选）
              <input
                type="datetime-local"
                aria-describedby="plan-time-zone-hint"
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
          {submitState.status === 'rejected' ? <p role="alert">{submitState.message}</p> : null}
          {submitState.status === 'unknown' ? <p role="alert">{submitState.message}</p> : null}
          <div className="wizard-actions">
            <button
              type="submit"
              disabled={
                !canSubmitPlan(submitState) ||
                catalog.status !== 'ready' ||
                catalog.items.length === 0
              }
            >
              {submitting
                ? '正在保存计划…'
                : submitState.status === 'rejected' || submitState.status === 'unknown'
                  ? '重试保存计划'
                  : '保存计划并继续'}
            </button>
          </div>
          {submitState.status === 'unknown' ? (
            <Link to="/review-cases">返回审查活动，查看服务器结果</Link>
          ) : null}
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
