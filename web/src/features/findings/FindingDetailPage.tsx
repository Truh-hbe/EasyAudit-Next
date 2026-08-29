import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../../api/client'
import { nudgeFinding } from '../../api/collaboration'
import {
  addFindingParticipant,
  createActionItem,
  getFinding,
  getFindingActions,
  getFindingActivities,
  getFindingParticipantViews,
  getFindingSubmissions,
  getReviewCase,
  reopenFinding,
  searchFindingParticipantCandidates,
  submitFindingVerification,
  submitRectification,
  transitionFinding,
} from '../../api/product'
import type {
  ActionItemResponse,
  AssignmentCandidateResponse,
  FindingActivityResponse,
  FindingParticipantViewResponse,
  FindingResponse,
  ReviewCaseResponse,
  SubmissionResponse,
} from '../../api/product'
import { formatDateTime, lifecycleText } from '../../product/format'
import { resolveFindingScenarioAdapter } from '../../scenarios'
import type { ScenarioFindingCommandPorts } from '../../scenarios/registry'

type PrimaryState =
  | { status: 'loading'; findingId: string | undefined }
  | { status: 'unavailable'; findingId: string | undefined }
  | { status: 'error'; findingId: string | undefined; message: string }
  | { status: 'ready'; findingId: string; data: FindingResponse }

type ChildState<T> =
  | { status: 'idle' }
  | { status: 'loading'; findingId: string }
  | { status: 'unavailable'; findingId: string }
  | { status: 'error'; findingId: string; message: string }
  | { status: 'ready'; findingId: string; data: T }

type CandidateState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: AssignmentCandidateResponse[] }

const idleChild = { status: 'idle' } as const

function unavailable(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404)
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function stateForFinding<T>(state: ChildState<T>, findingId: string): ChildState<T> {
  return state.status !== 'idle' && state.findingId === findingId ? state : idleChild
}

function actorKindText(actorKind: 'user' | 'department'): string {
  return actorKind === 'user' ? '用户' : '部门'
}

function ActivitySection({ state }: { state: ChildState<FindingActivityResponse[]> }) {
  return (
    <section className="surface-card" aria-labelledby="finding-activity-title">
      <h2 id="finding-activity-title">Finding Activity</h2>
      {state.status === 'idle' || state.status === 'loading' ? <p>正在读取 Activity…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">Activity 不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? (
        <p className="empty-note">暂无 Finding-subject Activity。</p>
      ) : null}
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

function SubmissionSection({ state }: { state: ChildState<SubmissionResponse[]> }) {
  return (
    <section className="surface-card" aria-labelledby="submission-history-title">
      <h2 id="submission-history-title">正式 Submission 历史</h2>
      {state.status === 'idle' || state.status === 'loading' ? <p>正在读取 Submission…</p> : null}
      {state.status === 'unavailable' ? <p className="empty-note">Submission 历史不可用。</p> : null}
      {state.status === 'error' ? <p role="alert">{state.message}</p> : null}
      {state.status === 'ready' && state.data.length === 0 ? (
        <p className="empty-note">暂无 Finding Submission。</p>
      ) : null}
      {state.status === 'ready' && state.data.length > 0 ? (
        <ol className="surface-list">
          {state.data.map((submission) => (
            <li key={submission.id}>
              <strong>{submission.purpose}</strong>
              <span>{formatDateTime(submission.submitted_at)}</span>
              <span>提交人 {submission.submitted_by}</span>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="empty-note">历史 payload 不用于推断当前生命周期或权限。</p>
    </section>
  )
}

export function FindingDetailPage() {
  const { findingId } = useParams()
  const currentFindingIdRef = useRef(findingId)
  currentFindingIdRef.current = findingId
  const candidateSearchSequenceRef = useRef(0)
  const [revision, setRevision] = useState(0)
  const [primary, setPrimary] = useState<PrimaryState>({
    status: 'loading',
    findingId: undefined,
  })
  const [reviewCase, setReviewCase] = useState<ChildState<ReviewCaseResponse>>(idleChild)
  const [participants, setParticipants] = useState<
    ChildState<FindingParticipantViewResponse[]>
  >(idleChild)
  const [actions, setActions] = useState<ChildState<ActionItemResponse[]>>(idleChild)
  const [submissions, setSubmissions] = useState<ChildState<SubmissionResponse[]>>(idleChild)
  const [activities, setActivities] = useState<ChildState<FindingActivityResponse[]>>(idleChild)
  const [candidateState, setCandidateState] = useState<CandidateState>({ status: 'idle' })
  const [candidateQuery, setCandidateQuery] = useState('')
  const [participantRoleKey, setParticipantRoleKey] = useState('')
  const [actionTitle, setActionTitle] = useState('')
  const [actionDueAt, setActionDueAt] = useState('')
  const [commandBusy, setCommandBusy] = useState(false)
  const [commandMessage, setCommandMessage] = useState<string | null>(null)
  const [nudgeBusy, setNudgeBusy] = useState(false)
  const [nudgeMessage, setNudgeMessage] = useState<string | null>(null)

  useEffect(() => {
    candidateSearchSequenceRef.current += 1
    setCandidateState({ status: 'idle' })
    setCandidateQuery('')
    setParticipantRoleKey('')
    setActionTitle('')
    setActionDueAt('')
    setCommandBusy(false)
    setCommandMessage(null)
    setNudgeBusy(false)
    setNudgeMessage(null)
  }, [findingId])

  useEffect(() => {
    setReviewCase(idleChild)
    setParticipants(idleChild)
    setActions(idleChild)
    setSubmissions(idleChild)
    setActivities(idleChild)
    setCandidateState({ status: 'idle' })

    if (findingId === undefined) {
      setPrimary({ status: 'unavailable', findingId })
      return
    }

    const requestedFindingId = findingId
    const controller = new AbortController()
    setPrimary({ status: 'loading', findingId: requestedFindingId })
    void getFinding(requestedFindingId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setPrimary({ status: 'ready', findingId: requestedFindingId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setPrimary(
          unavailable(error)
            ? { status: 'unavailable', findingId: requestedFindingId }
            : {
                status: 'error',
                findingId: requestedFindingId,
                message: errorMessage(error, 'Finding 请求失败'),
              },
        )
      })
    return () => controller.abort()
  }, [findingId, revision])

  const primaryMatchesRoute = primary.findingId === findingId
  const authorizedFindingId =
    primaryMatchesRoute && primary.status === 'ready' ? primary.data.id : null

  useEffect(() => {
    if (authorizedFindingId === null || primary.status !== 'ready') return
    const currentFinding = primary.data
    const controller = new AbortController()
    setReviewCase({ status: 'loading', findingId: authorizedFindingId })
    setParticipants({ status: 'loading', findingId: authorizedFindingId })
    setActions({ status: 'loading', findingId: authorizedFindingId })
    setSubmissions({ status: 'loading', findingId: authorizedFindingId })
    setActivities({ status: 'loading', findingId: authorizedFindingId })

    void getReviewCase(currentFinding.case_id, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setReviewCase({ status: 'ready', findingId: authorizedFindingId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setReviewCase(
          unavailable(error)
            ? { status: 'unavailable', findingId: authorizedFindingId }
            : {
                status: 'error',
                findingId: authorizedFindingId,
                message: errorMessage(error, 'ReviewCase 请求失败'),
              },
        )
      })

    void getFindingParticipantViews(authorizedFindingId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setParticipants({ status: 'ready', findingId: authorizedFindingId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setParticipants(
          unavailable(error)
            ? { status: 'unavailable', findingId: authorizedFindingId }
            : {
                status: 'error',
                findingId: authorizedFindingId,
                message: errorMessage(error, '参与人请求失败'),
              },
        )
      })

    void getFindingActions(authorizedFindingId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setActions({ status: 'ready', findingId: authorizedFindingId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setActions(
          unavailable(error)
            ? { status: 'unavailable', findingId: authorizedFindingId }
            : {
                status: 'error',
                findingId: authorizedFindingId,
                message: errorMessage(error, 'Action 请求失败'),
              },
        )
      })

    void getFindingSubmissions(authorizedFindingId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setSubmissions({ status: 'ready', findingId: authorizedFindingId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setSubmissions(
          unavailable(error)
            ? { status: 'unavailable', findingId: authorizedFindingId }
            : {
                status: 'error',
                findingId: authorizedFindingId,
                message: errorMessage(error, 'Submission 请求失败'),
              },
        )
      })

    void getFindingActivities(authorizedFindingId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setActivities({ status: 'ready', findingId: authorizedFindingId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setActivities(
          unavailable(error)
            ? { status: 'unavailable', findingId: authorizedFindingId }
            : {
                status: 'error',
                findingId: authorizedFindingId,
                message: errorMessage(error, 'Activity 请求失败'),
              },
        )
      })

    return () => controller.abort()
  }, [authorizedFindingId, primary])

  async function runCommand(label: string, command: () => Promise<unknown>) {
    const commandFindingId = findingId
    setCommandBusy(true)
    setCommandMessage(null)
    try {
      await command()
      if (currentFindingIdRef.current !== commandFindingId) return
      setCommandMessage(`${label}已由服务器确认。`)
      setCandidateState({ status: 'idle' })
      setRevision((value) => value + 1)
    } catch (error) {
      if (currentFindingIdRef.current !== commandFindingId) return
      setCommandMessage(errorMessage(error, `${label}失败`))
      if (error instanceof ApiError && [403, 409, 422].includes(error.status)) {
        setRevision((value) => value + 1)
      }
    } finally {
      if (currentFindingIdRef.current === commandFindingId) {
        setCommandBusy(false)
      }
    }
  }

  async function runNudge(currentFindingId: string) {
    const commandFindingId = findingId
    setNudgeBusy(true)
    setNudgeMessage(null)
    try {
      const result = await nudgeFinding(currentFindingId)
      if (currentFindingIdRef.current !== commandFindingId) return
      setNudgeMessage(
        `服务器已确认催办：${result.recipient_count} 位接收人，Activity ${result.activity_id}。`,
      )
      setRevision((value) => value + 1)
    } catch (error) {
      if (currentFindingIdRef.current !== commandFindingId) return
      setNudgeMessage(errorMessage(error, 'Finding 催办失败'))
      if (error instanceof ApiError && error.status === 404) {
        setRevision((value) => value + 1)
      }
    } finally {
      if (currentFindingIdRef.current === commandFindingId) {
        setNudgeBusy(false)
      }
    }
  }

  if (!primaryMatchesRoute || primary.status === 'loading') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.3</p>
        <h1>Finding</h1>
        <p>正在确认当前 Finding 授权…</p>
      </section>
    )
  }

  if (primary.status === 'unavailable') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.3</p>
        <h1>Finding 不可用</h1>
        <p>当前服务器未提供此 Finding 的可见内容。</p>
      </section>
    )
  }

  if (primary.status === 'error') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.3</p>
        <h1>Finding</h1>
        <div role="alert" className="surface-card">
          <p>{primary.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>
            重新加载
          </button>
        </div>
      </section>
    )
  }

  const finding = primary.data
  const caseState = stateForFinding(reviewCase, finding.id)
  const participantState = stateForFinding(participants, finding.id)
  const actionState = stateForFinding(actions, finding.id)
  const submissionState = stateForFinding(submissions, finding.id)
  const activityState = stateForFinding(activities, finding.id)
  const caseContext = caseState.status === 'ready' ? caseState.data : null
  const scenarioAdapter =
    caseContext === null
      ? undefined
      : resolveFindingScenarioAdapter(caseContext.scenario_key, caseContext.scenario_version)
  const participantOption =
    scenarioAdapter?.participantOptions.find((option) => option.roleKey === participantRoleKey) ??
    scenarioAdapter?.participantOptions[0]
  const FindingScenarioSection = scenarioAdapter?.FindingScenarioSection
  const FindingInteractionSection = scenarioAdapter?.FindingInteractionSection

  const interactionCommands: ScenarioFindingCommandPorts = {
    transition: (action, reason) => transitionFinding(finding.id, action, reason ?? null),
    submitRectification: (action, payload) => submitRectification(finding.id, action, payload),
    submitVerification: (action, payload) =>
      submitFindingVerification(finding.id, action, payload),
    reopen: (reason) => reopenFinding(finding.id, reason),
  }

  async function searchParticipants() {
    if (participantOption === undefined) return
    if (candidateQuery.trim().length < 2) {
      setCandidateState({ status: 'error', message: '候选搜索至少输入 2 个字符。' })
      return
    }
    const searchSequence = candidateSearchSequenceRef.current + 1
    candidateSearchSequenceRef.current = searchSequence
    const searchFindingId = findingId
    setCandidateState({ status: 'loading' })
    try {
      const data = await searchFindingParticipantCandidates(
        finding.id,
        participantOption.roleKey,
        participantOption.actorKind,
        candidateQuery,
      )
      if (
        currentFindingIdRef.current !== searchFindingId ||
        candidateSearchSequenceRef.current !== searchSequence
      ) {
        return
      }
      setCandidateState({ status: 'ready', data })
    } catch (error) {
      if (
        currentFindingIdRef.current !== searchFindingId ||
        candidateSearchSequenceRef.current !== searchSequence
      ) {
        return
      }
      setCandidateState({ status: 'error', message: errorMessage(error, '候选搜索失败') })
    }
  }

  return (
    <article className="surface-page" aria-labelledby="finding-title">
      <header className="case-header surface-card">
        <div>
          <p className="eyebrow">Finding · {finding.severity}</p>
          <h1 id="finding-title">{finding.title}</h1>
          <p>
            <Link to={`/review-cases/${finding.case_id}`}>返回 ReviewCase</Link>
          </p>
        </div>
        <span className="status-pill">{lifecycleText(finding.lifecycle)}</span>
      </header>

      <section className="surface-card" aria-labelledby="finding-overview-title">
        <h2 id="finding-overview-title">概览</h2>
        <dl className="fact-grid">
          <div>
            <dt>Finding ID</dt>
            <dd>{finding.id}</dd>
          </div>
          <div>
            <dt>ReviewCase</dt>
            <dd>{finding.case_id}</dd>
          </div>
          <div>
            <dt>提出时间</dt>
            <dd>{formatDateTime(finding.raised_at)}</dd>
          </div>
          <div>
            <dt>提出人</dt>
            <dd>{finding.raised_by}</dd>
          </div>
          <div className="wide-fact">
            <dt>描述</dt>
            <dd>{finding.description ?? '—'}</dd>
          </div>
        </dl>
      </section>

      {caseState.status === 'loading' || caseState.status === 'idle' ? (
        <section className="surface-card">
          <p>正在解析精确 Scenario UI…</p>
        </section>
      ) : null}
      {caseState.status === 'unavailable' || caseState.status === 'error' ? (
        <section className="surface-card">
          <h2>Scenario 信息</h2>
          <p className="empty-note">
            当前 Scenario 上下文不可用，Scenario-specific 编辑已关闭。
          </p>
        </section>
      ) : null}
      {caseContext !== null && FindingScenarioSection === undefined ? (
        <section className="surface-card">
          <h2>Scenario 信息</h2>
          <p role="status">
            不支持当前精确 Scenario UI：{caseContext.scenario_key}@
            {caseContext.scenario_version}。通用 Finding 信息仍可查看。
          </p>
        </section>
      ) : null}
      {FindingScenarioSection === undefined ? null : (
        <FindingScenarioSection finding={finding} />
      )}

      <section className="surface-card" aria-labelledby="participants-title">
        <div className="section-heading">
          <h2 id="participants-title">参与关系</h2>
        </div>
        {participantState.status === 'idle' || participantState.status === 'loading' ? (
          <p>正在读取参与关系…</p>
        ) : null}
        {participantState.status === 'unavailable' ? (
          <p className="empty-note">参与关系不可用。</p>
        ) : null}
        {participantState.status === 'error' ? <p role="alert">{participantState.message}</p> : null}
        {participantState.status === 'ready' && participantState.data.length === 0 ? (
          <p className="empty-note">暂无参与关系。</p>
        ) : null}
        {participantState.status === 'ready' && participantState.data.length > 0 ? (
          <ul className="surface-list">
            {participantState.data.map((participant) => (
              <li
                key={`${participant.actor_kind}-${participant.actor_id}-${participant.role_key}`}
              >
                <strong>{participant.display_name}</strong>
                <span>
                  {participant.role_key} · {actorKindText(participant.actor_kind)}
                </span>
                <span>加入于 {formatDateTime(participant.assigned_at)}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {scenarioAdapter !== undefined && !['closed', 'voided'].includes(finding.lifecycle) ? (
          <div className="subsurface">
            <h3>添加参与人</h3>
            <div className="form-grid">
              <label>
                关系角色
                <select
                  value={participantOption?.roleKey ?? ''}
                  onChange={(event) => {
                    setParticipantRoleKey(event.target.value)
                    candidateSearchSequenceRef.current += 1
                    setCandidateState({ status: 'idle' })
                  }}
                  disabled={commandBusy}
                >
                  {scenarioAdapter.participantOptions.map((option) => (
                    <option key={option.roleKey} value={option.roleKey}>
                      {option.label} · {actorKindText(option.actorKind)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                搜索
                <input
                  value={candidateQuery}
                  onChange={(event) => setCandidateQuery(event.target.value)}
                  disabled={commandBusy}
                  placeholder="至少 2 个字符"
                />
              </label>
            </div>
            <button
              type="button"
              className="secondary"
              onClick={() => void searchParticipants()}
              disabled={commandBusy}
            >
              搜索候选
            </button>
            {candidateState.status === 'loading' ? <p>正在查询当前目标允许的候选…</p> : null}
            {candidateState.status === 'error' ? <p role="alert">{candidateState.message}</p> : null}
            {candidateState.status === 'ready' && candidateState.data.length === 0 ? (
              <p className="empty-note">没有匹配候选。</p>
            ) : null}
            {candidateState.status === 'ready' && candidateState.data.length > 0 ? (
              <ul className="surface-list candidate-list">
                {candidateState.data.map((candidate) => (
                  <li key={`${candidate.actor_kind}-${candidate.actor_id}`}>
                    <strong>{candidate.display_name}</strong>
                    <span>{actorKindText(candidate.actor_kind)}</span>
                    <button
                      type="button"
                      onClick={() =>
                        void runCommand('添加参与人', () =>
                          addFindingParticipant(
                            finding.id,
                            candidate.actor_kind,
                            candidate.actor_id,
                            participantOption?.roleKey ?? '',
                          ),
                        )
                      }
                      disabled={commandBusy || participantOption === undefined}
                    >
                      添加
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="surface-card" aria-labelledby="actions-title">
        <h2 id="actions-title">Action Items</h2>
        {actionState.status === 'idle' || actionState.status === 'loading' ? (
          <p>正在读取 Action Items…</p>
        ) : null}
        {actionState.status === 'unavailable' ? (
          <p className="empty-note">Action Items 不可用。</p>
        ) : null}
        {actionState.status === 'error' ? <p role="alert">{actionState.message}</p> : null}
        {actionState.status === 'ready' && actionState.data.length === 0 ? (
          <p className="empty-note">暂无 Action Item。</p>
        ) : null}
        {actionState.status === 'ready' && actionState.data.length > 0 ? (
          <ul className="surface-list">
            {actionState.data.map((action) => (
              <li key={action.id}>
                <Link to={`/action-items/${action.id}`}>{action.title}</Link>
                <span>
                  {lifecycleText(action.lifecycle)} · due {formatDateTime(action.due_at)}
                </span>
                <span>completed {formatDateTime(action.completed_at)}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {scenarioAdapter !== undefined && finding.lifecycle === 'rectifying' ? (
          <form
            className="command-form subsurface"
            onSubmit={(event) => {
              event.preventDefault()
              const dueAt =
                actionDueAt.length === 0 ? null : new Date(actionDueAt).toISOString()
              void runCommand('创建 Action Item', () =>
                createActionItem(finding.id, { title: actionTitle, due_at: dueAt }),
              )
            }}
          >
            <h3>新建 Action Item</h3>
            <div className="form-grid">
              <label>
                标题
                <input
                  value={actionTitle}
                  onChange={(event) => setActionTitle(event.target.value)}
                  disabled={commandBusy}
                />
              </label>
              <label>
                到期时间
                <input
                  type="datetime-local"
                  value={actionDueAt}
                  onChange={(event) => setActionDueAt(event.target.value)}
                  disabled={commandBusy}
                />
              </label>
            </div>
            <button type="submit" disabled={commandBusy}>
              创建
            </button>
          </form>
        ) : null}
      </section>

      {FindingInteractionSection === undefined ? null : (
        <FindingInteractionSection
          key={finding.id}
          finding={finding}
          disabled={commandBusy}
          commands={interactionCommands}
          execute={runCommand}
        />
      )}
      {commandMessage === null ? null : <p role="status">{commandMessage}</p>}

      <section className="surface-card" aria-labelledby="finding-nudge-title">
        <h2 id="finding-nudge-title">协作提醒</h2>
        <p className="empty-note">
          按钮不证明催办权限，也不选择接收人；服务器按当前 exact Scenario 与关系事实重新授权并解析 recipient。
        </p>
        <button
          type="button"
          className="secondary"
          disabled={nudgeBusy}
          onClick={() => void runNudge(finding.id)}
        >
          {nudgeBusy ? '正在催办…' : '催一下'}
        </button>
        {nudgeMessage === null ? null : <p role="status">{nudgeMessage}</p>}
      </section>

      <SubmissionSection state={submissionState} />
      <ActivitySection state={activityState} />
    </article>
  )
}
