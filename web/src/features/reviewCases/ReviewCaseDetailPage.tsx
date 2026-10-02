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
import { formatDateTime } from '../../product/format'
import { scenarioName, scenarioVersionText } from '../../product/terms'
import { ActivityEventName } from '../../ui/ActivityEventName'
import { isDeadlineStatus, StatusTag } from '../../ui/StatusTag'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import { FindingCreatePanel } from '../findings/FindingCreatePanel'
import { ReviewCaseTeamPanel } from './ReviewCaseTeamPanel'

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

function FindingSection({ state }: { state: SectionState<FindingResponse[]> }) {
  return (
    <section className="surface-card" aria-labelledby="findings-title">
      <h2 id="findings-title">发现项</h2>
      {state.status === 'loading' || state.status === 'idle' ? <p>正在读取发现项…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">发现项列表不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? <p className="empty-note">暂无发现项。</p> : null}
      {state.status === 'ready' && state.data.length > 0 ? (
        <ul className="surface-list">
          {state.data.map((finding) => (
            <li key={finding.id}>
              <Link to={`/findings/${finding.id}`}>{finding.title}</Link>
              <span>严重度 <StatusTag kind="severity" value={finding.severity} /> <StatusTag kind="finding" value={finding.lifecycle} /></span>
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
      <h2 id="activity-title">操作记录</h2>
      {state.status === 'loading' || state.status === 'idle' ? <p>正在读取操作记录…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">操作记录不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? <p className="empty-note">暂无操作记录。</p> : null}
      {state.status === 'ready' && state.data.length > 0 ? (
        <ol className="activity-list">
          {state.data.map((activity) => (
            <li key={activity.id}>
              <ActivityEventName eventType={activity.event_type} />
              <span>{formatDateTime(activity.occurred_at)}</span>
              <span>操作人 {activity.actor_id ?? '系统'}</span>
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
          <div><dt>截止状态</dt><dd>{isDeadlineStatus(state.data.case.deadline_bucket) ? <StatusTag kind="deadline" value={state.data.case.deadline_bucket} /> : '未临近截止'}</dd></div>
          <div><dt>发现项</dt><dd>{state.data.case.findings.total}</dd></div>
          <div><dt>待处理 / 整改中 / 待验证</dt><dd>{state.data.case.findings.open} / {state.data.case.findings.rectifying} / {state.data.case.findings.verifying}</dd></div>
          <div><dt>整改项</dt><dd>{state.data.case.actions.total}</dd></div>
          <div><dt>整改项已逾期</dt><dd>{state.data.case.actions.overdue}</dd></div>
          <div><dt>整改项即将到期</dt><dd>{state.data.case.actions.due_soon}</dd></div>
        </dl>
      ) : null}
    </section>
  )
}

export function ReviewCaseDetailPage() {
  const { caseId } = useParams()
  const [revision, setRevision] = useState(0)
  const [teamRevision, setTeamRevision] = useState(0)
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
          message: sectionMessage(error, '审查活动请求失败'),
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
    setActivities({ status: 'loading', caseId: authorizedCaseId })

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
                message: sectionMessage(error, '操作记录请求失败'),
              },
        )
      })

    return () => controller.abort()
  }, [authorizedCaseId, teamRevision])

  useEffect(() => {
    if (authorizedCaseId === null) return
    const controller = new AbortController()
    setFindings({ status: 'loading', caseId: authorizedCaseId })
    setManagement({ status: 'loading', caseId: authorizedCaseId })

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
                message: sectionMessage(error, '发现项请求失败'),
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
    return <section className="surface-page"><h1>审查活动</h1><p>正在确认访问权限…</p></section>
  }

  if (primary.status === 'unavailable') {
    return <section className="surface-page"><h1>审查活动不可用</h1><p>当前没有可见的审查活动内容。</p></section>
  }

  if (primary.status === 'error') {
    return (
      <section className="surface-page">
        <h1>审查活动</h1>
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
  const memberData = memberState.status === 'ready' ? memberState.data : []

  return (
    <article className="surface-page" aria-labelledby="case-title">
      <header className="case-header surface-card">
        <div>
          <p className="eyebrow">{scenarioName(reviewCase.scenario_key)}</p>
          <h1 id="case-title">{reviewCase.title}</h1>
        </div>
        <StatusTag kind="reviewCase" value={reviewCase.lifecycle} />
      </header>

      <section className="surface-card" aria-labelledby="overview-title">
        <h2 id="overview-title">概览</h2>
        <dl className="fact-grid">
          <div><dt>审查活动 ID</dt><dd>{reviewCase.id}</dd></div>
          <div><dt>场景版本</dt><dd>{scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}</dd></div>
          <div><dt>审查计划</dt><dd>{reviewCase.plan_id ?? '—'}</dd></div>
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
          <h2 id="scenario-unsupported-title">审查场景</h2>
          <p role="status">暂不支持当前版本的审查场景界面（{scenarioName(reviewCase.scenario_key)} · {scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}）。仍可查看审查活动的通用信息。</p>
        </section>
      ) : (
        <ScenarioSection reviewCase={reviewCase} />
      )}

      <ManagementProgressSection state={managementState} />
      <FindingCreatePanel reviewCase={reviewCase} />
      <FindingSection state={findingState} />
      <ReviewCaseTeamPanel
        reviewCase={reviewCase}
        roleOptions={scenarioAdapter?.caseMemberRoleOptions ?? []}
        members={memberData}
        membersLoading={memberState.status === 'loading' || memberState.status === 'idle'}
        membersUnavailable={memberState.status === 'unavailable'}
        membersError={memberState.status === 'error' ? memberState.message : null}
        onTeamChanged={() => setTeamRevision((value) => value + 1)}
      />
      <ActivitySection state={activityState} />
    </article>
  )
}
