import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../../api/client'
import { nudgeActionItem, nudgeFinding } from '../../api/collaboration'
import type { NudgeResponse } from '../../api/collaboration'
import { getManagedReviewCaseProgress } from '../../api/management'
import type { ManagementCaseProgressResponse } from '../../api/product'
import { formatDateTime, lifecycleText } from '../../product/format'

type ProgressState =
  | { status: 'loading'; caseId: string | undefined }
  | { status: 'unavailable'; caseId: string | undefined }
  | { status: 'error'; caseId: string | undefined; message: string }
  | { status: 'ready'; caseId: string; data: ManagementCaseProgressResponse }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function ManagementCaseProgressPage() {
  const { caseId } = useParams()
  const currentCaseIdRef = useRef(caseId)
  currentCaseIdRef.current = caseId
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<ProgressState>({ status: 'loading', caseId: undefined })
  const [nudgeBusyKey, setNudgeBusyKey] = useState<string | null>(null)
  const [nudgeMessage, setNudgeMessage] = useState<string | null>(null)

  useEffect(() => {
    setNudgeBusyKey(null)
    setNudgeMessage(null)
    if (caseId === undefined) {
      setState({ status: 'unavailable', caseId })
      return
    }

    const requestedCaseId = caseId
    const controller = new AbortController()
    setState({ status: 'loading', caseId: requestedCaseId })
    void getManagedReviewCaseProgress(requestedCaseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', caseId: requestedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState(
          error instanceof ApiError && error.status === 404
            ? { status: 'unavailable', caseId: requestedCaseId }
            : {
                status: 'error',
                caseId: requestedCaseId,
                message: errorMessage(error, '管理进度请求失败'),
              },
        )
      })
    return () => controller.abort()
  }, [caseId, revision])

  async function runNudge(
    key: string,
    command: () => Promise<NudgeResponse>,
  ) {
    const commandCaseId = caseId
    setNudgeBusyKey(key)
    setNudgeMessage(null)
    try {
      const result = await command()
      if (currentCaseIdRef.current !== commandCaseId) return
      setNudgeMessage(
        `服务器已确认催办：${result.recipient_count} 位接收人，Activity ${result.activity_id}。`,
      )
      setRevision((value) => value + 1)
    } catch (error) {
      if (currentCaseIdRef.current !== commandCaseId) return
      setNudgeMessage(errorMessage(error, '催办失败'))
      if (error instanceof ApiError && error.status === 404) {
        setRevision((value) => value + 1)
      }
    } finally {
      if (currentCaseIdRef.current === commandCaseId) {
        setNudgeBusyKey(null)
      }
    }
  }

  const matchesRoute = state.caseId === caseId
  if (!matchesRoute || state.status === 'loading') {
    return <section className="surface-page"><p className="eyebrow">M3.5.4</p><h1>管理进度</h1><p>正在读取 M3.3 服务器投影…</p></section>
  }

  if (state.status === 'unavailable') {
    return <section className="surface-page"><p className="eyebrow">M3.5.4</p><h1>管理进度不可用</h1><p>当前服务器未提供此 ReviewCase 的管理投影。</p></section>
  }

  if (state.status === 'error') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.4</p>
        <h1>管理进度</h1>
        <div role="alert" className="surface-card">
          <p>{state.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </div>
      </section>
    )
  }

  const data = state.data
  return (
    <section className="surface-page" aria-labelledby="management-progress-title">
      <header className="case-header surface-card">
        <div>
          <p className="eyebrow">M3.5.4 · server as_of {formatDateTime(data.as_of)}</p>
          <h1 id="management-progress-title">{data.case.title}</h1>
          <p><Link to="/management">返回管理视图</Link> · <Link to={`/review-cases/${data.case.id}`}>打开原 ReviewCase</Link></p>
        </div>
        <span className="status-pill">{lifecycleText(data.case.lifecycle)}</span>
      </header>

      <section className="surface-card" aria-labelledby="progress-summary-title">
        <h2 id="progress-summary-title">服务器进度事实</h2>
        <dl className="fact-grid">
          <div><dt>Deadline bucket</dt><dd>{data.case.deadline_bucket}</dd></div>
          <div><dt>计划结束</dt><dd>{formatDateTime(data.case.planned_end_at)}</dd></div>
          <div><dt>Finding total</dt><dd>{data.case.findings.total}</dd></div>
          <div><dt>Finding closed</dt><dd>{data.case.findings.closed}</dd></div>
          <div><dt>Action total</dt><dd>{data.case.actions.total}</dd></div>
          <div><dt>Action done</dt><dd>{data.case.actions.done}</dd></div>
          <div><dt>Action overdue</dt><dd>{data.case.actions.overdue}</dd></div>
          <div><dt>Action due soon</dt><dd>{data.case.actions.due_soon}</dd></div>
        </dl>
        <p className="empty-note">本页不从这些计数生成百分比、风险分或新的 deadline truth。</p>
      </section>

      <section className="surface-card" aria-labelledby="managed-findings-title">
        <h2 id="managed-findings-title">授权可见的 Findings</h2>
        {data.findings.length === 0 ? <p className="empty-note">当前投影没有可见 Finding。</p> : (
          <ul className="surface-list">
            {data.findings.map((finding) => {
              const key = `finding:${finding.id}`
              return (
                <li key={finding.id}>
                  <Link to={`/findings/${finding.id}`}>{finding.title}</Link>
                  <span>{finding.severity} · {lifecycleText(finding.lifecycle)}</span>
                  <span>提出于 {formatDateTime(finding.raised_at)}</span>
                  <span>
                    Actions: total {finding.actions.total} / todo {finding.actions.todo} / in progress {finding.actions.in_progress} / done {finding.actions.done} / overdue {finding.actions.overdue} / due soon {finding.actions.due_soon}
                  </span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nudgeBusyKey !== null}
                    onClick={() => void runNudge(key, () => nudgeFinding(finding.id))}
                  >
                    {nudgeBusyKey === key ? '正在催办…' : '催一下 Finding'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="surface-card" aria-labelledby="overdue-actions-title">
        <h2 id="overdue-actions-title">已逾期 Actions</h2>
        {data.overdue_actions.length === 0 ? <p className="empty-note">服务器当前没有已逾期 Action。</p> : (
          <ul className="surface-list">
            {data.overdue_actions.map((action) => {
              const key = `action:${action.id}`
              return (
                <li key={action.id}>
                  <Link to={`/action-items/${action.id}`}>{action.title}</Link>
                  <span>{lifecycleText(action.lifecycle)} · {formatDateTime(action.due_at)}</span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nudgeBusyKey !== null}
                    onClick={() => void runNudge(key, () => nudgeActionItem(action.id))}
                  >
                    {nudgeBusyKey === key ? '正在催办…' : '催一下 Action'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="surface-card" aria-labelledby="due-soon-actions-title">
        <h2 id="due-soon-actions-title">即将到期 Actions</h2>
        {data.due_soon_actions.length === 0 ? <p className="empty-note">服务器当前没有即将到期 Action。</p> : (
          <ul className="surface-list">
            {data.due_soon_actions.map((action) => {
              const key = `action:${action.id}`
              return (
                <li key={action.id}>
                  <Link to={`/action-items/${action.id}`}>{action.title}</Link>
                  <span>{lifecycleText(action.lifecycle)} · {formatDateTime(action.due_at)}</span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nudgeBusyKey !== null}
                    onClick={() => void runNudge(key, () => nudgeActionItem(action.id))}
                  >
                    {nudgeBusyKey === key ? '正在催办…' : '催一下 Action'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <p className="empty-note">管理行只提供原 Finding/Action 命令的快捷入口；recipient 仍由 M3.4 exact Scenario 在服务器解析。</p>
      {nudgeMessage === null ? null : <p role="status">{nudgeMessage}</p>}
    </section>
  )
}
