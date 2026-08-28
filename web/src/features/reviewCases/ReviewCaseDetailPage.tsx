import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../../api/client'
import {
  getManagementCaseProgress,
  getReviewCase,
  getReviewCaseActivities,
  getReviewCaseFindings,
  getReviewCaseMembers,
} from '../../api/product'
import type {
  CaseMemberViewResponse,
  FindingResponse,
  ManagementCaseProgressResponse,
  ReviewCaseActivityResponse,
  ReviewCaseResponse,
} from '../../api/product'
import { formatDateTime, lifecycleText } from '../../product/format'
import { resolveCaseScenarioAdapter } from '../../scenarios'

type PrimaryState =
  | { status: 'loading'; caseId: string | undefined }
  | { status: 'unavailable'; caseId: string | undefined }
  | { status: 'error'; caseId: string | undefined; message: string }
  | { status: 'ready'; caseId: string; data: ReviewCaseResponse }

type SectionState<T> =
  | { status: 'idle' }
  | { status: 'loading'; caseId: string }
  | { status: 'unavailable'; caseId: string }
  | { status: 'error'; caseId: string; message: string }
  | { status: 'ready'; caseId: string; data: T }

const idleSection = { status: 'idle' } as const

function sectionMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function unavailable(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404)
}

function stateForCase<T>(state: SectionState<T>, caseId: string): SectionState<T> {
  return state.status !== 'idle' && state.caseId === caseId ? state : idleSection
}

function MemberSection({ state }: { state: SectionState<CaseMemberViewResponse[]> }) {
  return (
    <section className="surface-card" aria-labelledby="members-title">
      <h2 id="members-title">成员</h2>
      {state.status === 'loading' || state.status === 'idle' ? <p>正在读取成员…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">成员信息不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? <p className="empty-note">暂无 CaseMember。</p> : null}
      {state.status === 'ready' && state.data.length > 0 ? (
        <ul className="surface-list">
          {state.data.map((member) => (
            <li key={`${member.user_id}-${member.role_key}`}>
              <strong>{member.display_name}</strong>
              <span>{member.role_key}</span>
              <span>加入于 {formatDateTime(member.joined_at)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function FindingSection({ state }: { state: SectionState<FindingResponse[]> }) {
  return (
    <section className="surface-card" aria-labelledby="findings-title">
      <h2 id="findings-title">Findings</h2>
      {state.status === 'loading' || state.status === 'idle' ? <p>正在读取 Findings…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">Finding 列表不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? <p className="empty-note">暂无 Finding。</p> : null}
      {state.status === 'ready' && state.data.length > 0 ? (
        <ul className="surface-list">
          {state.data.map((finding) => (
            <li key={finding.id}>
              <Link to={`/findings/${finding.id}`}>{finding.title}</Link>
              <span>{finding.severity} · {lifecycleText(finding.lifecycle)}</span>
              <span>提出于 {formatDateTime(finding.raised_at)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function ActivitySection({ state }: { state: SectionState<ReviewCaseActivityResponse[]> }) {
  return (
    <section className="surface-card" aria-labelledby="activity-title">
      <h2 id="activity-title">Activity</h2>
      {state.status === 'loading' || state.status === 'idle' ? <p>正在读取 Case Activity…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">Activity 不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? <p className="empty-note">暂无 ReviewCase Activity。</p> : null}
      {state.status === 'ready' && state.data.length > 0 ? (
        <ol className="activity-list">
          {state.data.map((activity) => (
            <li key={activity.id}>
              <strong>{activity.event_type}</strong>
              <span>{formatDateTime(activity.occurred_at)}</span>
              <span>Actor {activity.actor_id ?? 'system'}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  )
}

function ManagementProgressSection({ state }: { state: SectionState<ManagementCaseProgressResponse> }) {
  return (
    <section className="surface-card" aria-labelledby="management-progress-title">
      <h2 id="management-progress-title">管理进度</h2>
      {state.status === 'loading' || state.status === 'idle' ? <p>正在确认管理进度可见性…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">当前用户没有可用的管理进度摘要。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' ? (
        <dl className="fact-grid compact-facts">
          <div><dt>Deadline</dt><dd>{state.data.case.deadline_bucket}</dd></div>
          <div><dt>Findings</dt><dd>{state.data.case.findings.total}</dd></div>
          <div><dt>Open / Rectifying / Verifying</dt><dd>{state.data.case.findings.open} / {state.data.case.findings.rectifying} / {state.data.case.findings.verifying}</dd></div>
          <div><dt>Actions</dt><dd>{state.data.case.actions.total}</dd></div>
          <div><dt>Action overdue</dt><dd>{state.data.case.actions.overdue}</dd></div>
          <div><dt>Action due soon</dt><dd>{state.data.case.actions.due_soon}</dd></div>
        </dl>
      ) : null}
    </section>
  )
}

export function ReviewCaseDetailPage() {
  const { caseId } = useParams()
  const [revision, setRevision] = useState(0)
  const [primary, setPrimary] = useState<PrimaryState>({ status: 'loading', caseId: undefined })
  const [members, setMembers] = useState<SectionState<CaseMemberViewResponse[]>>(idleSection)
  const [findings, setFindings] = useState<SectionState<FindingResponse[]>>(idleSection)
  const [activities, setActivities] = useState<SectionState<ReviewCaseActivityResponse[]>>(idleSection)
  const [management, setManagement] = useState<SectionState<ManagementCaseProgressResponse>>(idleSection)

  useEffect(() => {
    setMembers(idleSection)
    setFindings(idleSection)
    setActivities(idleSection)
    setManagement(idleSection)

    if (caseId === undefined) {
      setPrimary({ status: 'unavailable', caseId })
      return
    }

    const requestedCaseId = caseId
    const controller = new AbortController()
    setPrimary({ status: 'loading', caseId: requestedCaseId })
    void getReviewCase(requestedCaseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setPrimary({ status: 'ready', caseId: requestedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (unavailable(error)) {
          setPrimary({ status: 'unavailable', caseId: requestedCaseId })
          return
        }
        setPrimary({
          status: 'error',
          caseId: requestedCaseId,
          message: sectionMessage(error, 'ReviewCase 请求失败'),
        })
      })
    return () => controller.abort()
  }, [caseId, revision])

  const primaryMatchesRoute = primary.caseId === caseId
  const authorizedCaseId =
    primaryMatchesRoute && primary.status === 'ready' ? primary.data.id : null
  useEffect(() => {
    if (authorizedCaseId === null) return
    const controller = new AbortController()
    setMembers({ status: 'loading', caseId: authorizedCaseId })
    setFindings({ status: 'loading', caseId: authorizedCaseId })
    setActivities({ status: 'loading', caseId: authorizedCaseId })
    setManagement({ status: 'loading', caseId: authorizedCaseId })

    void getReviewCaseMembers(authorizedCaseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setMembers({ status: 'ready', caseId: authorizedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setMembers(
          unavailable(error)
            ? { status: 'unavailable', caseId: authorizedCaseId }
            : {
                status: 'error',
                caseId: authorizedCaseId,
                message: sectionMessage(error, '成员请求失败'),
              },
        )
      })

    void getReviewCaseFindings(authorizedCaseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setFindings({ status: 'ready', caseId: authorizedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setFindings(
          unavailable(error)
            ? { status: 'unavailable', caseId: authorizedCaseId }
            : {
                status: 'error',
                caseId: authorizedCaseId,
                message: sectionMessage(error, 'Finding 请求失败'),
              },
        )
      })

    void getReviewCaseActivities(authorizedCaseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setActivities({ status: 'ready', caseId: authorizedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setActivities(
          unavailable(error)
            ? { status: 'unavailable', caseId: authorizedCaseId }
            : {
                status: 'error',
                caseId: authorizedCaseId,
                message: sectionMessage(error, 'Activity 请求失败'),
              },
        )
      })

    void getManagementCaseProgress(authorizedCaseId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setManagement({ status: 'ready', caseId: authorizedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setManagement(
          unavailable(error)
            ? { status: 'unavailable', caseId: authorizedCaseId }
            : {
                status: 'error',
                caseId: authorizedCaseId,
                message: sectionMessage(error, '管理进度请求失败'),
              },
        )
      })

    return () => controller.abort()
  }, [authorizedCaseId])

  if (!primaryMatchesRoute || primary.status === 'loading') {
    return <section className="surface-page"><p className="eyebrow">M3.5.2</p><h1>ReviewCase</h1><p>正在确认当前 ReviewCase 授权…</p></section>
  }

  if (primary.status === 'unavailable') {
    return <section className="surface-page"><p className="eyebrow">M3.5.2</p><h1>ReviewCase 不可用</h1><p>当前服务器未提供此 ReviewCase 的可见内容。</p></section>
  }

  if (primary.status === 'error') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.2</p>
        <h1>ReviewCase</h1>
        <div role="alert" className="surface-card">
          <p>{primary.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </div>
      </section>
    )
  }

  const reviewCase = primary.data
  const scenarioAdapter = resolveCaseScenarioAdapter(reviewCase.scenario_key, reviewCase.scenario_version)
  const ScenarioSection = scenarioAdapter?.CaseScenarioSection
  const memberState = stateForCase(members, reviewCase.id)
  const findingState = stateForCase(findings, reviewCase.id)
  const activityState = stateForCase(activities, reviewCase.id)
  const managementState = stateForCase(management, reviewCase.id)

  return (
    <article className="surface-page" aria-labelledby="case-title">
      <header className="case-header surface-card">
        <div>
          <p className="eyebrow">{reviewCase.scenario_key}@{reviewCase.scenario_version}</p>
          <h1 id="case-title">{reviewCase.title}</h1>
        </div>
        <span className="status-pill">{lifecycleText(reviewCase.lifecycle)}</span>
      </header>

      <section className="surface-card" aria-labelledby="overview-title">
        <h2 id="overview-title">概览</h2>
        <dl className="fact-grid">
          <div><dt>ReviewCase ID</dt><dd>{reviewCase.id}</dd></div>
          <div><dt>ReviewPlan</dt><dd>{reviewCase.plan_id ?? '—'}</dd></div>
          <div><dt>计划开始</dt><dd>{formatDateTime(reviewCase.planned_start_at)}</dd></div>
          <div><dt>计划结束</dt><dd>{formatDateTime(reviewCase.planned_end_at)}</dd></div>
          <div><dt>实际开始</dt><dd>{formatDateTime(reviewCase.started_at)}</dd></div>
          <div><dt>现场完成</dt><dd>{formatDateTime(reviewCase.fieldwork_completed_at)}</dd></div>
          <div><dt>关闭</dt><dd>{formatDateTime(reviewCase.closed_at)}</dd></div>
          <div><dt>创建</dt><dd>{formatDateTime(reviewCase.created_at)}</dd></div>
        </dl>
      </section>

      {ScenarioSection === undefined ? (
        <section className="surface-card" aria-labelledby="scenario-unsupported-title">
          <h2 id="scenario-unsupported-title">Scenario 信息</h2>
          <p role="status">不支持当前精确 Scenario UI：{reviewCase.scenario_key}@{reviewCase.scenario_version}。通用 Case 信息仍可查看。</p>
        </section>
      ) : (
        <ScenarioSection reviewCase={reviewCase} />
      )}

      <ManagementProgressSection state={managementState} />
      <FindingSection state={findingState} />
      <MemberSection state={memberState} />
      <ActivitySection state={activityState} />
    </article>
  )
}
