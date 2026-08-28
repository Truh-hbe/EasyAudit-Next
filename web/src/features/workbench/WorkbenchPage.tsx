import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { getWorkbench } from '../../api/product'
import type {
  WorkbenchActionDeadline,
  WorkbenchActionResponsibility,
  WorkbenchCaseDeadline,
  WorkbenchCaseResponsibility,
  WorkbenchFindingResponsibility,
  WorkbenchResponse,
  WorkbenchVerificationItem,
} from '../../api/product'
import { formatDateTime, lifecycleText } from '../../product/format'

type WorkbenchState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: WorkbenchResponse }

function CaseRows({ items }: { items: WorkbenchCaseResponsibility[] }) {
  if (items.length === 0) return <p className="empty-note">暂无我参与的审查。</p>
  return (
    <ul className="surface-list">
      {items.map((item) => (
        <li key={item.id}>
          <Link to={`/review-cases/${item.id}`}>{item.title}</Link>
          <span>{lifecycleText(item.lifecycle)}</span>
          <span>计划结束 {formatDateTime(item.planned_end_at)}</span>
          <span>关系 {item.role_keys.join(' / ') || '—'}</span>
        </li>
      ))}
    </ul>
  )
}

function FindingRows({ items }: { items: WorkbenchFindingResponsibility[] }) {
  if (items.length === 0) return <p className="empty-note">暂无 Finding 责任。</p>
  return (
    <ul className="surface-list">
      {items.map((item) => (
        <li key={item.id}>
          <Link to={`/findings/${item.id}`}>{item.title}</Link>
          <span>{item.severity} · {lifecycleText(item.lifecycle)}</span>
          <span>提出于 {formatDateTime(item.raised_at)}</span>
        </li>
      ))}
    </ul>
  )
}

function ActionRows({ items }: { items: WorkbenchActionResponsibility[] }) {
  if (items.length === 0) return <p className="empty-note">暂无 Action 责任。</p>
  return (
    <ul className="surface-list">
      {items.map((item) => (
        <li key={item.id}>
          <Link to={`/action-items/${item.id}`}>{item.title}</Link>
          <span>{lifecycleText(item.lifecycle)}</span>
          <span>到期 {formatDateTime(item.due_at)}</span>
        </li>
      ))}
    </ul>
  )
}

function VerificationRows({ items }: { items: WorkbenchVerificationItem[] }) {
  if (items.length === 0) return <p className="empty-note">暂无待验证 Finding。</p>
  return (
    <ul className="surface-list">
      {items.map((item) => (
        <li key={item.id}>
          <Link to={`/findings/${item.id}`}>{item.title}</Link>
          <span>{item.severity}</span>
          <span>提出于 {formatDateTime(item.raised_at)}</span>
        </li>
      ))}
    </ul>
  )
}

function DeadlineRows({
  cases,
  actions,
  emptyText,
}: {
  cases: WorkbenchCaseDeadline[]
  actions: WorkbenchActionDeadline[]
  emptyText: string
}) {
  if (cases.length === 0 && actions.length === 0) return <p className="empty-note">{emptyText}</p>
  return (
    <ul className="surface-list">
      {cases.map((item) => (
        <li key={`case-${item.id}`}>
          <Link to={`/review-cases/${item.id}`}>{item.title}</Link>
          <span>Case · {lifecycleText(item.lifecycle)}</span>
          <span>{formatDateTime(item.deadline)}</span>
        </li>
      ))}
      {actions.map((item) => (
        <li key={`action-${item.id}`}>
          <Link to={`/action-items/${item.id}`}>{item.title}</Link>
          <span>Action · {lifecycleText(item.lifecycle)}</span>
          <span>{formatDateTime(item.deadline)}</span>
        </li>
      ))}
    </ul>
  )
}

export function WorkbenchPage() {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<WorkbenchState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    void getWorkbench(controller.signal)
      .then((data) => setState({ status: 'ready', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'Workbench 请求失败',
        })
      })
    return () => controller.abort()
  }, [revision])

  if (state.status === 'loading') {
    return <section className="surface-page"><p className="eyebrow">M3.5.2</p><h1>我的工作</h1><p>正在读取服务器 Workbench…</p></section>
  }

  if (state.status === 'error') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.2</p>
        <h1>我的工作</h1>
        <div role="alert" className="surface-card">
          <p>{state.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </div>
      </section>
    )
  }

  const { data } = state
  return (
    <section className="surface-page" aria-labelledby="workbench-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">M3.5.2 · server projection</p>
          <h1 id="workbench-title">我的工作</h1>
        </div>
        <p>数据时间 {formatDateTime(data.as_of)}</p>
      </div>

      <div className="surface-grid">
        <section className="surface-card"><h2>待我验证</h2><VerificationRows items={data.verification_queue} /></section>
        <section className="surface-card"><h2>Finding 责任</h2><FindingRows items={data.finding_responsibilities} /></section>
        <section className="surface-card"><h2>Action 责任</h2><ActionRows items={data.action_responsibilities} /></section>
        <section className="surface-card"><h2>已逾期</h2><DeadlineRows cases={data.overdue.cases} actions={data.overdue.actions} emptyText="暂无已逾期事项。" /></section>
        <section className="surface-card"><h2>即将到期</h2><DeadlineRows cases={data.due_soon.cases} actions={data.due_soon.actions} emptyText="暂无即将到期事项。" /></section>
        <section className="surface-card"><h2>我参与的审查</h2><CaseRows items={data.case_responsibilities} /></section>
      </div>
    </section>
  )
}
