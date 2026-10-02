import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { listReviewCases } from '../../api/product'
import type { ReviewCaseCollectionResponse } from '../../api/product'
import { formatDateTime } from '../../product/format'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { ButtonLink } from '../../ui/ButtonLink'
import { StatusTag } from '../../ui/StatusTag'

type CollectionState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: ReviewCaseCollectionResponse }

function boundedInteger(raw: string | null, fallback: number, minimum: number, maximum: number): number {
  if (raw === null || raw.trim() === '') return fallback
  const parsed = Number.parseInt(raw, 10)
  if (!Number.isInteger(parsed)) return fallback
  return Math.min(maximum, Math.max(minimum, parsed))
}

function nonNegativeInteger(raw: string | null): number {
  if (raw === null || raw.trim() === '') return 0
  const parsed = Number.parseInt(raw, 10)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0
}

export function ReviewCaseCollectionPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedLimit = useMemo(() => boundedInteger(searchParams.get('limit'), 50, 1, 100), [searchParams])
  const requestedOffset = useMemo(() => nonNegativeInteger(searchParams.get('offset')), [searchParams])
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<CollectionState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    void listReviewCases(requestedLimit, requestedOffset, controller.signal)
      .then((data) => setState({ status: 'ready', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : '审查活动列表请求失败',
        })
      })
    return () => controller.abort()
  }, [requestedLimit, requestedOffset, revision])

  function moveTo(offset: number, limit: number): void {
    setSearchParams({ limit: String(limit), offset: String(Math.max(0, offset)) })
  }

  if (state.status === 'loading') {
    return <section className="surface-page"><h1>审查活动</h1><p>正在读取审查活动…</p></section>
  }

  if (state.status === 'error') {
    return (
      <section className="surface-page">
        <h1>审查活动</h1>
        <div role="alert" className="surface-card">
          <p>{state.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </div>
      </section>
    )
  }

  const { data } = state
  const pageEnd = Math.min(data.offset + data.items.length, data.total)
  return (
    <section className="surface-page" aria-labelledby="review-case-list-title">
      <div className="page-heading">
        <div>
          <h1 id="review-case-list-title">审查活动</h1>
        </div>
        <div className="heading-actions">
          <ButtonLink type="primary" to="/review-plans/new">新建审查计划</ButtonLink>
          <p>已授权 {data.total} 项</p>
        </div>
      </div>

      {data.items.length === 0 ? (
        <div className="surface-card"><p className="empty-note">当前页面没有可见的审查活动。</p></div>
      ) : (
        <div className="surface-card">
          <ul className="case-list">
            {data.items.map((reviewCase) => (
              <li key={reviewCase.id}>
                <div>
                  <Link className="case-title-link" to={`/review-cases/${reviewCase.id}`}>{reviewCase.title}</Link>
                  <p>{scenarioName(reviewCase.scenario_key)} · {scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}</p>
                </div>
                <span><StatusTag kind="reviewCase" value={reviewCase.lifecycle} /></span>
                <span>计划开始 {formatDateTime(reviewCase.planned_start_at)}</span>
                <span>计划结束 {formatDateTime(reviewCase.planned_end_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <nav className="pagination" aria-label="审查活动分页">
        <button
          type="button"
          disabled={data.offset === 0}
          onClick={() => moveTo(data.offset - data.limit, data.limit)}
        >
          上一页
        </button>
        <span>{data.total === 0 ? '0' : `${data.offset + 1}–${pageEnd}`} / {data.total}</span>
        <button
          type="button"
          disabled={data.offset + data.items.length >= data.total}
          onClick={() => moveTo(data.offset + data.limit, data.limit)}
        >
          下一页
        </button>
      </nav>
    </section>
  )
}
