import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import {
  exportManagedReviewCases,
  listManagedReviewCases,
} from '../../api/management'
import type {
  ManagementCaseCollectionResponse,
  ManagementDeadlineFilter,
  ManagementExportFormat,
} from '../../api/management'
import type { ReviewCaseLifecycle } from '../../api/product'
import { formatDateTime, lifecycleText } from '../../product/format'

type ManagementState =
  | { status: 'loading'; key: string }
  | { status: 'error'; key: string; message: string }
  | { status: 'ready'; key: string; data: ManagementCaseCollectionResponse }

const PAGE_SIZE = 20

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function saveFile(file: { blob: Blob; filename: string }): void {
  const url = URL.createObjectURL(file.blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = file.filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function deadlineText(bucket: 'overdue' | 'due_soon' | 'later' | 'none'): string {
  const labels = {
    overdue: '已逾期',
    due_soon: '即将到期',
    later: '稍后到期',
    none: '无当前期限',
  } as const
  return labels[bucket]
}

export function ManagementPage() {
  const [lifecycle, setLifecycle] = useState<ReviewCaseLifecycle | ''>('')
  const [deadlineStatus, setDeadlineStatus] = useState<ManagementDeadlineFilter>('all')
  const [reviewPlanInput, setReviewPlanInput] = useState('')
  const [reviewPlanId, setReviewPlanId] = useState('')
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const requestSequenceRef = useRef(0)
  const [exporting, setExporting] = useState<ManagementExportFormat | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  const queryKey = `${reviewPlanId}:${lifecycle}:${deadlineStatus}:${offset}`
  const [state, setState] = useState<ManagementState>({ status: 'loading', key: queryKey })

  useEffect(() => {
    const controller = new AbortController()
    const sequence = requestSequenceRef.current + 1
    requestSequenceRef.current = sequence
    const requestedKey = queryKey
    setState({ status: 'loading', key: requestedKey })

    void listManagedReviewCases(
      {
        reviewPlanId: reviewPlanId.length === 0 ? undefined : reviewPlanId,
        lifecycle: lifecycle === '' ? undefined : lifecycle,
        deadlineStatus,
        limit: PAGE_SIZE,
        offset,
      },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({ status: 'ready', key: requestedKey, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({
          status: 'error',
          key: requestedKey,
          message: errorMessage(error, '管理视图请求失败'),
        })
      })

    return () => controller.abort()
  }, [deadlineStatus, lifecycle, offset, queryKey, reviewPlanId, revision])

  function exportCases(format: ManagementExportFormat) {
    setExporting(format)
    setExportError(null)
    // The export is a server snapshot of the same filters, not of the page being shown.
    void exportManagedReviewCases(format, {
      reviewPlanId: reviewPlanId.length === 0 ? undefined : reviewPlanId,
      lifecycle: lifecycle === '' ? undefined : lifecycle,
      deadlineStatus,
    })
      .then(saveFile)
      .catch((error: unknown) => setExportError(errorMessage(error, '导出失败')))
      .finally(() => setExporting(null))
  }

  const currentState = state.key === queryKey ? state : { status: 'loading', key: queryKey } as const
  const data = currentState.status === 'ready' ? currentState.data : null
  const canPrevious = offset > 0
  const canNext = data !== null && data.offset + data.items.length < data.total

  return (
    <section className="surface-page" aria-labelledby="management-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">M3.5.4 · M3.3 server projection</p>
          <h1 id="management-title">管理视图</h1>
        </div>
        <p>投影时间 {formatDateTime(data?.as_of ?? null)}</p>
      </div>

      <section className="surface-card" aria-labelledby="management-filters-title">
        <h2 id="management-filters-title">服务器筛选</h2>
        <div className="form-grid">
          <label>
            Case lifecycle
            <select
              value={lifecycle}
              onChange={(event) => {
                setLifecycle(event.target.value as ReviewCaseLifecycle | '')
                setOffset(0)
              }}
            >
              <option value="">全部</option>
              <option value="draft">draft</option>
              <option value="scheduled">scheduled</option>
              <option value="in_progress">in_progress</option>
              <option value="awaiting_closure">awaiting_closure</option>
              <option value="closed">closed</option>
              <option value="cancelled">cancelled</option>
            </select>
          </label>
          <label>
            Deadline
            <select
              value={deadlineStatus}
              onChange={(event) => {
                setDeadlineStatus(event.target.value as ManagementDeadlineFilter)
                setOffset(0)
              }}
            >
              <option value="all">全部</option>
              <option value="due_soon">即将到期</option>
              <option value="overdue">已逾期</option>
            </select>
          </label>
          <label>
            ReviewPlan ID
            <input
              value={reviewPlanInput}
              onChange={(event) => setReviewPlanInput(event.target.value)}
              placeholder="可选 UUID"
            />
          </label>
        </div>
        <div className="command-stack">
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setReviewPlanId(reviewPlanInput.trim())
              setOffset(0)
            }}
          >应用 ReviewPlan</button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setReviewPlanInput('')
              setReviewPlanId('')
              setLifecycle('')
              setDeadlineStatus('all')
              setOffset(0)
            }}
          >清除筛选</button>
        </div>
        <div className="command-stack">
          <button
            type="button"
            className="secondary"
            disabled={exporting !== null}
            onClick={() => exportCases('csv')}
          >{exporting === 'csv' ? '正在导出…' : '导出 CSV'}</button>
          <button
            type="button"
            className="secondary"
            disabled={exporting !== null}
            onClick={() => exportCases('xlsx')}
          >{exporting === 'xlsx' ? '正在导出…' : '导出 XLSX'}</button>
        </div>
        {exportError !== null ? <p role="alert">{exportError}</p> : null}
        <p className="empty-note">筛选、授权、deadline bucket、聚合、total 与分页都由 M3.3 服务器 read side 决定。</p>
      </section>

      {currentState.status === 'loading' ? (
        <section className="surface-card"><p>正在读取授权后的管理集合…</p></section>
      ) : null}

      {currentState.status === 'error' ? (
        <section className="surface-card" role="alert">
          <p>{currentState.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </section>
      ) : null}

      {data !== null ? (
        <section className="surface-card" aria-labelledby="management-results-title">
          <div className="section-heading">
            <h2 id="management-results-title">我可管理的 ReviewCases</h2>
            <span>服务器 total {data.total}</span>
          </div>
          {data.items.length === 0 ? <p className="empty-note">当前筛选下没有授权后的 ReviewCase。</p> : (
            <ul className="surface-list">
              {data.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.scenario_key}@{item.scenario_version}</p>
                  </div>
                  <span>{lifecycleText(item.lifecycle)} · {deadlineText(item.deadline_bucket)}</span>
                  <span>计划结束 {formatDateTime(item.planned_end_at)}</span>
                  <span>
                    Findings: total {item.findings.total} / open {item.findings.open} / rectifying {item.findings.rectifying} / verifying {item.findings.verifying} / closed {item.findings.closed} / voided {item.findings.voided}
                  </span>
                  <span>
                    Actions: total {item.actions.total} / todo {item.actions.todo} / in progress {item.actions.in_progress} / done {item.actions.done} / cancelled {item.actions.cancelled} / overdue {item.actions.overdue} / due soon {item.actions.due_soon}
                  </span>
                  <div className="command-stack">
                    <Link to={`/management/review-cases/${item.id}`}>查看管理进度</Link>
                    <Link to={`/review-cases/${item.id}`}>打开原 ReviewCase</Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {data !== null ? (
        <section className="surface-card" aria-label="管理视图分页">
          <p>服务器 offset {data.offset} · limit {data.limit} · total {data.total}</p>
          <div className="command-stack">
            <button
              type="button"
              className="secondary"
              disabled={!canPrevious}
              onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
            >上一页</button>
            <button
              type="button"
              className="secondary"
              disabled={!canNext}
              onClick={() => setOffset((value) => value + PAGE_SIZE)}
            >下一页</button>
          </div>
        </section>
      ) : null}
    </section>
  )
}
