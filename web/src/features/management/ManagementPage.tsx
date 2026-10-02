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
import type { DeadlineBucket, ReviewCaseLifecycle } from '../../api/product'
import { formatDateTime } from '../../product/format'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { isDeadlineStatus, StatusTag, statusLabel } from '../../ui/StatusTag'

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

function DeadlineBucketText({ bucket }: { bucket: DeadlineBucket }) {
  if (isDeadlineStatus(bucket)) return <StatusTag kind="deadline" value={bucket} />
  return <>{bucket === 'later' ? '稍后到期' : '无当前期限'}</>
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
          <h1 id="management-title">管理视图</h1>
        </div>
        <p>数据时间 {formatDateTime(data?.as_of ?? null)}</p>
      </div>

      <section className="surface-card" aria-labelledby="management-filters-title">
        <h2 id="management-filters-title">筛选条件</h2>
        <div className="form-grid">
          <label>
            审查活动状态
            <select
              value={lifecycle}
              onChange={(event) => {
                setLifecycle(event.target.value as ReviewCaseLifecycle | '')
                setOffset(0)
              }}
            >
              <option value="">全部</option>
              <option value="draft">{statusLabel('reviewCase', 'draft')}</option>
              <option value="scheduled">{statusLabel('reviewCase', 'scheduled')}</option>
              <option value="in_progress">{statusLabel('reviewCase', 'in_progress')}</option>
              <option value="awaiting_closure">{statusLabel('reviewCase', 'awaiting_closure')}</option>
              <option value="closed">{statusLabel('reviewCase', 'closed')}</option>
              <option value="cancelled">{statusLabel('reviewCase', 'cancelled')}</option>
            </select>
          </label>
          <label>
            截止情况
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
            审查计划 ID
            <input
              value={reviewPlanInput}
              onChange={(event) => setReviewPlanInput(event.target.value)}
              placeholder="可选，填写审查计划 ID"
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
          >按审查计划筛选</button>
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
        <p className="empty-note">筛选、授权、截止分组、汇总与分页均以服务器结果为准。</p>
      </section>

      {currentState.status === 'loading' ? (
        <section className="surface-card"><p>正在读取管理视图…</p></section>
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
            <h2 id="management-results-title">我可管理的审查活动</h2>
            <span>共 {data.total} 项</span>
          </div>
          {data.items.length === 0 ? <p className="empty-note">当前筛选下没有可管理的审查活动。</p> : (
            <ul className="surface-list">
              {data.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{scenarioName(item.scenario_key)} · {scenarioVersionText(item.scenario_key, item.scenario_version)}</p>
                  </div>
                  <span><StatusTag kind="reviewCase" value={item.lifecycle} /> <DeadlineBucketText bucket={item.deadline_bucket} /></span>
                  <span>计划结束 {formatDateTime(item.planned_end_at)}</span>
                  <span>
                    发现项：共 {item.findings.total} / 待处理 {item.findings.open} / 整改中 {item.findings.rectifying} / 待验证 {item.findings.verifying} / 已关闭 {item.findings.closed} / 已作废 {item.findings.voided}
                  </span>
                  <span>
                    整改项：共 {item.actions.total} / 待开始 {item.actions.todo} / 执行中 {item.actions.in_progress} / 已完成 {item.actions.done} / 已取消 {item.actions.cancelled} / 已逾期 {item.actions.overdue} / 即将到期 {item.actions.due_soon}
                  </span>
                  <div className="command-stack">
                    <Link to={`/management/review-cases/${item.id}`}>查看管理进度</Link>
                    <Link to={`/review-cases/${item.id}`}>打开审查活动</Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {data !== null ? (
        <section className="surface-card" aria-label="管理视图分页">
          <p>第 {data.total === 0 ? 0 : data.offset + 1}–{data.offset + data.items.length} 项 · 共 {data.total} 项</p>
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
