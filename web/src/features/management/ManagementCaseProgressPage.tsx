import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../../api/client'
import { nudgeActionItem, nudgeFinding } from '../../api/collaboration'
import type { NudgeResponse } from '../../api/collaboration'
import { getManagedReviewCaseProgress } from '../../api/management'
import type { ManagementCaseProgressResponse } from '../../api/product'
import { formatDateTime } from '../../product/format'
import { isDeadlineStatus, StatusTag } from '../../ui/StatusTag'

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
  }, [caseId])

  useEffect(() => {
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
        `服务器已确认催办：已通知 ${result.recipient_count} 人，操作记录 ${result.activity_id}。`,
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
    return <section className="surface-page"><h1>管理进度</h1><p>正在读取管理进度…</p></section>
  }

  if (state.status === 'unavailable') {
    return <section className="surface-page"><h1>管理进度不可用</h1><p>当前没有此审查活动的管理进度。</p></section>
  }

  if (state.status === 'error') {
    return (
      <section className="surface-page">
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
          <p className="eyebrow">数据时间 {formatDateTime(data.as_of)}</p>
          <h1 id="management-progress-title">{data.case.title}</h1>
          <p><Link to="/management">返回管理视图</Link> · <Link to={`/review-cases/${data.case.id}`}>打开审查活动</Link></p>
        </div>
        <StatusTag kind="reviewCase" value={data.case.lifecycle} />
      </header>

      <section className="surface-card" aria-labelledby="progress-summary-title">
        <h2 id="progress-summary-title">进度概况</h2>
        <dl className="fact-grid">
          <div><dt>截止状态</dt><dd>{isDeadlineStatus(data.case.deadline_bucket) ? <StatusTag kind="deadline" value={data.case.deadline_bucket} /> : '未临近截止'}</dd></div>
          <div><dt>计划结束</dt><dd>{formatDateTime(data.case.planned_end_at)}</dd></div>
          <div><dt>发现项总数</dt><dd>{data.case.findings.total}</dd></div>
          <div><dt>发现项已关闭</dt><dd>{data.case.findings.closed}</dd></div>
          <div><dt>整改项总数</dt><dd>{data.case.actions.total}</dd></div>
          <div><dt>整改项已完成</dt><dd>{data.case.actions.done}</dd></div>
          <div><dt>整改项已逾期</dt><dd>{data.case.actions.overdue}</dd></div>
          <div><dt>整改项即将到期</dt><dd>{data.case.actions.due_soon}</dd></div>
        </dl>
        <p className="empty-note">本页只展示服务器给出的计数，不计算百分比、风险分或截止状态。</p>
      </section>

      <section className="surface-card" aria-labelledby="managed-findings-title">
        <h2 id="managed-findings-title">可见的发现项</h2>
        {data.findings.length === 0 ? <p className="empty-note">当前没有可见的发现项。</p> : (
          <ul className="surface-list">
            {data.findings.map((finding) => {
              const key = `finding:${finding.id}`
              return (
                <li key={finding.id}>
                  <Link to={`/findings/${finding.id}`}>{finding.title}</Link>
                  <span>严重度 <StatusTag kind="severity" value={finding.severity} /> <StatusTag kind="finding" value={finding.lifecycle} /></span>
                  <span>提出于 {formatDateTime(finding.raised_at)}</span>
                  <span>
                    整改项：共 {finding.actions.total} / 待开始 {finding.actions.todo} / 执行中 {finding.actions.in_progress} / 已完成 {finding.actions.done} / 已逾期 {finding.actions.overdue} / 即将到期 {finding.actions.due_soon}
                  </span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nudgeBusyKey !== null}
                    onClick={() => void runNudge(key, () => nudgeFinding(finding.id))}
                  >
                    {nudgeBusyKey === key ? '正在催办…' : '催办发现项'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="surface-card" aria-labelledby="overdue-actions-title">
        <h2 id="overdue-actions-title">已逾期整改项</h2>
        {data.overdue_actions.length === 0 ? <p className="empty-note">当前没有已逾期整改项。</p> : (
          <ul className="surface-list">
            {data.overdue_actions.map((action) => {
              const key = `action:${action.id}`
              return (
                <li key={action.id}>
                  <Link to={`/action-items/${action.id}`}>{action.title}</Link>
                  <span><StatusTag kind="actionItem" value={action.lifecycle} /> 到期 {formatDateTime(action.due_at)}</span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nudgeBusyKey !== null}
                    onClick={() => void runNudge(key, () => nudgeActionItem(action.id))}
                  >
                    {nudgeBusyKey === key ? '正在催办…' : '催办整改项'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="surface-card" aria-labelledby="due-soon-actions-title">
        <h2 id="due-soon-actions-title">即将到期整改项</h2>
        {data.due_soon_actions.length === 0 ? <p className="empty-note">当前没有即将到期整改项。</p> : (
          <ul className="surface-list">
            {data.due_soon_actions.map((action) => {
              const key = `action:${action.id}`
              return (
                <li key={action.id}>
                  <Link to={`/action-items/${action.id}`}>{action.title}</Link>
                  <span><StatusTag kind="actionItem" value={action.lifecycle} /> 到期 {formatDateTime(action.due_at)}</span>
                  <button
                    type="button"
                    className="secondary"
                    disabled={nudgeBusyKey !== null}
                    onClick={() => void runNudge(key, () => nudgeActionItem(action.id))}
                  >
                    {nudgeBusyKey === key ? '正在催办…' : '催办整改项'}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <p className="empty-note">此处只提供催办入口；被催办的人由服务器按审查场景确定。</p>
      {nudgeMessage === null ? null : <p role="status">{nudgeMessage}</p>}
    </section>
  )
}
