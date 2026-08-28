import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../../api/client'
import { nudgeActionItem } from '../../api/collaboration'
import {
  addActionAssignee,
  getActionAssigneeViews,
  getActionEvidences,
  getActionItem,
  getActionItemActivities,
  getFinding,
  getReviewCase,
  searchActionAssigneeCandidates,
  transitionActionItem,
} from '../../api/product'
import type {
  ActionAssigneeViewResponse,
  ActionItemActivityResponse,
  ActionItemResponse,
  AssignmentCandidateResponse,
  EvidenceResponse,
  FindingResponse,
  ReviewCaseResponse,
} from '../../api/product'
import { formatDateTime, lifecycleText } from '../../product/format'
import { resolveFindingScenarioAdapter } from '../../scenarios'

type PrimaryState =
  | { status: 'loading'; actionItemId: string | undefined }
  | { status: 'unavailable'; actionItemId: string | undefined }
  | { status: 'error'; actionItemId: string | undefined; message: string }
  | { status: 'ready'; actionItemId: string; data: ActionItemResponse }

type ChildState<T> =
  | { status: 'idle' }
  | { status: 'loading'; actionItemId: string }
  | { status: 'unavailable'; actionItemId: string }
  | { status: 'error'; actionItemId: string; message: string }
  | { status: 'ready'; actionItemId: string; data: T }

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

function stateForAction<T>(state: ChildState<T>, actionItemId: string): ChildState<T> {
  return state.status !== 'idle' && state.actionItemId === actionItemId ? state : idleChild
}

function actorKindText(actorKind: 'user' | 'department'): string {
  return actorKind === 'user' ? '用户' : '部门'
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function ActionItemDetailPage() {
  const { actionItemId } = useParams()
  const currentActionItemIdRef = useRef(actionItemId)
  currentActionItemIdRef.current = actionItemId
  const candidateSearchSequenceRef = useRef(0)
  const [revision, setRevision] = useState(0)
  const [primary, setPrimary] = useState<PrimaryState>({ status: 'loading', actionItemId: undefined })
  const [finding, setFinding] = useState<ChildState<FindingResponse>>(idleChild)
  const [reviewCase, setReviewCase] = useState<ChildState<ReviewCaseResponse>>(idleChild)
  const [assignees, setAssignees] = useState<ChildState<ActionAssigneeViewResponse[]>>(idleChild)
  const [evidences, setEvidences] = useState<ChildState<EvidenceResponse[]>>(idleChild)
  const [activities, setActivities] = useState<ChildState<ActionItemActivityResponse[]>>(idleChild)
  const [candidateState, setCandidateState] = useState<CandidateState>({ status: 'idle' })
  const [candidateQuery, setCandidateQuery] = useState('')
  const [assigneeRole, setAssigneeRole] = useState('')
  const [transitionReason, setTransitionReason] = useState('')
  const [commandBusy, setCommandBusy] = useState(false)
  const [commandMessage, setCommandMessage] = useState<string | null>(null)
  const [nudgeBusy, setNudgeBusy] = useState(false)
  const [nudgeMessage, setNudgeMessage] = useState<string | null>(null)

  useEffect(() => {
    candidateSearchSequenceRef.current += 1
    setCandidateState({ status: 'idle' })
    setCandidateQuery('')
    setAssigneeRole('')
    setTransitionReason('')
    setCommandBusy(false)
    setCommandMessage(null)
    setNudgeBusy(false)
    setNudgeMessage(null)
  }, [actionItemId])

  useEffect(() => {
    setFinding(idleChild)
    setReviewCase(idleChild)
    setAssignees(idleChild)
    setEvidences(idleChild)
    setActivities(idleChild)
    setCandidateState({ status: 'idle' })

    if (actionItemId === undefined) {
      setPrimary({ status: 'unavailable', actionItemId })
      return
    }

    const requestedId = actionItemId
    const controller = new AbortController()
    setPrimary({ status: 'loading', actionItemId: requestedId })
    void getActionItem(requestedId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setPrimary({ status: 'ready', actionItemId: requestedId, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setPrimary(
          unavailable(error)
            ? { status: 'unavailable', actionItemId: requestedId }
            : { status: 'error', actionItemId: requestedId, message: errorMessage(error, 'ActionItem 请求失败') },
        )
      })
    return () => controller.abort()
  }, [actionItemId, revision])

  const primaryMatchesRoute = primary.actionItemId === actionItemId
  const authorizedActionId =
    primaryMatchesRoute && primary.status === 'ready' ? primary.data.id : null

  useEffect(() => {
    if (authorizedActionId === null || primary.status !== 'ready') return
    const action = primary.data
    const controller = new AbortController()
    setFinding({ status: 'loading', actionItemId: authorizedActionId })
    setReviewCase({ status: 'loading', actionItemId: authorizedActionId })
    setAssignees({ status: 'loading', actionItemId: authorizedActionId })
    setEvidences({ status: 'loading', actionItemId: authorizedActionId })
    setActivities({ status: 'loading', actionItemId: authorizedActionId })

    void getFinding(action.finding_id, controller.signal)
      .then(async (findingData) => {
        if (controller.signal.aborted) return
        setFinding({ status: 'ready', actionItemId: authorizedActionId, data: findingData })
        try {
          const caseData = await getReviewCase(findingData.case_id, controller.signal)
          if (!controller.signal.aborted) setReviewCase({ status: 'ready', actionItemId: authorizedActionId, data: caseData })
        } catch (error) {
          if (controller.signal.aborted) return
          setReviewCase(
            unavailable(error)
              ? { status: 'unavailable', actionItemId: authorizedActionId }
              : { status: 'error', actionItemId: authorizedActionId, message: errorMessage(error, 'ReviewCase 请求失败') },
          )
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setFinding(
          unavailable(error)
            ? { status: 'unavailable', actionItemId: authorizedActionId }
            : { status: 'error', actionItemId: authorizedActionId, message: errorMessage(error, 'Finding 请求失败') },
        )
        setReviewCase({ status: 'unavailable', actionItemId: authorizedActionId })
      })

    void getActionAssigneeViews(authorizedActionId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setAssignees({ status: 'ready', actionItemId: authorizedActionId, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setAssignees(
          unavailable(error)
            ? { status: 'unavailable', actionItemId: authorizedActionId }
            : { status: 'error', actionItemId: authorizedActionId, message: errorMessage(error, '执行人请求失败') },
        )
      })

    void getActionEvidences(authorizedActionId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setEvidences({ status: 'ready', actionItemId: authorizedActionId, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setEvidences(
          unavailable(error)
            ? { status: 'unavailable', actionItemId: authorizedActionId }
            : { status: 'error', actionItemId: authorizedActionId, message: errorMessage(error, 'Evidence 请求失败') },
        )
      })

    void getActionItemActivities(authorizedActionId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setActivities({ status: 'ready', actionItemId: authorizedActionId, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setActivities(
          unavailable(error)
            ? { status: 'unavailable', actionItemId: authorizedActionId }
            : { status: 'error', actionItemId: authorizedActionId, message: errorMessage(error, 'Activity 请求失败') },
        )
      })

    return () => controller.abort()
  }, [authorizedActionId, primary])

  async function runCommand(label: string, command: () => Promise<unknown>) {
    const commandActionItemId = actionItemId
    setCommandBusy(true)
    setCommandMessage(null)
    try {
      await command()
      if (currentActionItemIdRef.current !== commandActionItemId) return
      setCommandMessage(`${label}已由服务器确认。`)
      setCandidateState({ status: 'idle' })
      setRevision((value) => value + 1)
    } catch (error) {
      if (currentActionItemIdRef.current !== commandActionItemId) return
      setCommandMessage(errorMessage(error, `${label}失败`))
      if (error instanceof ApiError && [403, 409, 422].includes(error.status)) {
        setRevision((value) => value + 1)
      }
    } finally {
      if (currentActionItemIdRef.current === commandActionItemId) {
        setCommandBusy(false)
      }
    }
  }

  async function runNudge(currentActionId: string) {
    const commandActionItemId = actionItemId
    setNudgeBusy(true)
    setNudgeMessage(null)
    try {
      const result = await nudgeActionItem(currentActionId)
      if (currentActionItemIdRef.current !== commandActionItemId) return
      setNudgeMessage(
        `服务器已确认催办：${result.recipient_count} 位接收人，Activity ${result.activity_id}。`,
      )
      setRevision((value) => value + 1)
    } catch (error) {
      if (currentActionItemIdRef.current !== commandActionItemId) return
      setNudgeMessage(errorMessage(error, 'Action 催办失败'))
      if (error instanceof ApiError && error.status === 404) {
        setRevision((value) => value + 1)
      }
    } finally {
      if (currentActionItemIdRef.current === commandActionItemId) {
        setNudgeBusy(false)
      }
    }
  }

  if (!primaryMatchesRoute || primary.status === 'loading') {
    return <section className="surface-page"><p className="eyebrow">M3.5.3</p><h1>Action Item</h1><p>正在确认当前 Action 授权…</p></section>
  }

  if (primary.status === 'unavailable') {
    return <section className="surface-page"><p className="eyebrow">M3.5.3</p><h1>Action Item 不可用</h1><p>当前服务器未提供此 Action 的可见内容。</p></section>
  }

  if (primary.status === 'error') {
    return (
      <section className="surface-page">
        <p className="eyebrow">M3.5.3</p><h1>Action Item</h1>
        <div role="alert" className="surface-card"><p>{primary.message}</p><button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button></div>
      </section>
    )
  }

  const action = primary.data
  const findingState = stateForAction(finding, action.id)
  const caseState = stateForAction(reviewCase, action.id)
  const assigneeState = stateForAction(assignees, action.id)
  const evidenceState = stateForAction(evidences, action.id)
  const activityState = stateForAction(activities, action.id)
  const caseContext = caseState.status === 'ready' ? caseState.data : null
  const scenarioAdapter = caseContext === null ? undefined : resolveFindingScenarioAdapter(caseContext.scenario_key, caseContext.scenario_version)
  const assigneeOption =
    scenarioAdapter?.assigneeOptions.find((option) => option.role === assigneeRole) ??
    scenarioAdapter?.assigneeOptions[0]

  async function searchAssignees() {
    if (assigneeOption === undefined) return
    if (candidateQuery.trim().length < 2) {
      setCandidateState({ status: 'error', message: '候选搜索至少输入 2 个字符。' })
      return
    }
    const searchSequence = candidateSearchSequenceRef.current + 1
    candidateSearchSequenceRef.current = searchSequence
    const searchActionItemId = actionItemId
    setCandidateState({ status: 'loading' })
    try {
      const data = await searchActionAssigneeCandidates(
        action.id,
        assigneeOption.role,
        assigneeOption.actorKind,
        candidateQuery,
      )
      if (
        currentActionItemIdRef.current !== searchActionItemId ||
        candidateSearchSequenceRef.current !== searchSequence
      ) return
      setCandidateState({ status: 'ready', data })
    } catch (error) {
      if (
        currentActionItemIdRef.current !== searchActionItemId ||
        candidateSearchSequenceRef.current !== searchSequence
      ) return
      setCandidateState({ status: 'error', message: errorMessage(error, '候选搜索失败') })
    }
  }

  return (
    <article className="surface-page" aria-labelledby="action-title">
      <header className="case-header surface-card">
        <div>
          <p className="eyebrow">Action Item</p>
          <h1 id="action-title">{action.title}</h1>
          <p><Link to={`/findings/${action.finding_id}`}>返回 Finding</Link></p>
        </div>
        <span className="status-pill">{lifecycleText(action.lifecycle)}</span>
      </header>

      <section className="surface-card" aria-labelledby="action-overview-title">
        <h2 id="action-overview-title">整改事项</h2>
        <dl className="fact-grid">
          <div><dt>Action ID</dt><dd>{action.id}</dd></div>
          <div><dt>Finding</dt><dd>{action.finding_id}</dd></div>
          <div><dt>到期时间</dt><dd>{formatDateTime(action.due_at)}</dd></div>
          <div><dt>完成时间</dt><dd>{formatDateTime(action.completed_at)}</dd></div>
        </dl>
        <p className="empty-note">到期时间按 wire fact 展示；本页不计算新的逾期规则。</p>
      </section>

      <section className="surface-card" aria-labelledby="action-parent-title">
        <h2 id="action-parent-title">所属 Finding</h2>
        {findingState.status === 'idle' || findingState.status === 'loading' ? <p>正在读取 Finding…</p> : null}
        {findingState.status === 'unavailable' ? <p className="empty-note">Finding 上下文不可用。</p> : null}
        {findingState.status === 'error' ? <p role="alert">{findingState.message}</p> : null}
        {findingState.status === 'ready' ? <p><Link to={`/findings/${findingState.data.id}`}>{findingState.data.title}</Link> · {lifecycleText(findingState.data.lifecycle)}</p> : null}
      </section>

      <section className="surface-card" aria-labelledby="assignees-title">
        <h2 id="assignees-title">执行关系</h2>
        {assigneeState.status === 'idle' || assigneeState.status === 'loading' ? <p>正在读取执行关系…</p> : null}
        {assigneeState.status === 'unavailable' ? <p className="empty-note">执行关系不可用。</p> : null}
        {assigneeState.status === 'error' ? <p role="alert">{assigneeState.message}</p> : null}
        {assigneeState.status === 'ready' && assigneeState.data.length === 0 ? <p className="empty-note">暂无执行人。</p> : null}
        {assigneeState.status === 'ready' && assigneeState.data.length > 0 ? (
          <ul className="surface-list">
            {assigneeState.data.map((assignee) => (
              <li key={`${assignee.actor_kind}-${assignee.actor_id}-${assignee.role}`}>
                <strong>{assignee.display_name}</strong>
                <span>{assignee.role} · {actorKindText(assignee.actor_kind)}</span>
                <span>加入于 {formatDateTime(assignee.assigned_at)}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {scenarioAdapter !== undefined && action.lifecycle !== 'cancelled' ? (
          <div className="subsurface">
            <h3>添加执行人</h3>
            <div className="form-grid">
              <label>
                执行角色
                <select
                  value={assigneeOption?.role ?? ''}
                  onChange={(event) => {
                    setAssigneeRole(event.target.value)
                    candidateSearchSequenceRef.current += 1
                    setCandidateState({ status: 'idle' })
                  }}
                  disabled={commandBusy}
                >
                  {scenarioAdapter.assigneeOptions.map((option) => <option key={option.role} value={option.role}>{option.label} · {actorKindText(option.actorKind)}</option>)}
                </select>
              </label>
              <label>搜索<input value={candidateQuery} onChange={(event) => setCandidateQuery(event.target.value)} disabled={commandBusy} placeholder="至少 2 个字符" /></label>
            </div>
            <button type="button" className="secondary" onClick={() => void searchAssignees()} disabled={commandBusy}>搜索候选</button>
            {candidateState.status === 'loading' ? <p>正在查询当前 Action 允许的候选…</p> : null}
            {candidateState.status === 'error' ? <p role="alert">{candidateState.message}</p> : null}
            {candidateState.status === 'ready' && candidateState.data.length === 0 ? <p className="empty-note">没有匹配候选。</p> : null}
            {candidateState.status === 'ready' && candidateState.data.length > 0 ? (
              <ul className="surface-list candidate-list">
                {candidateState.data.map((candidate) => (
                  <li key={`${candidate.actor_kind}-${candidate.actor_id}`}>
                    <strong>{candidate.display_name}</strong>
                    <span>{actorKindText(candidate.actor_kind)}</span>
                    <button type="button" onClick={() => void runCommand('添加执行人', () => addActionAssignee(action.id, candidate.actor_kind, candidate.actor_id, assigneeOption?.role ?? 'primary'))} disabled={commandBusy || assigneeOption === undefined}>添加</button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </section>

      {scenarioAdapter === undefined ? (
        <section className="surface-card"><h2>业务操作</h2><p className="empty-note">精确 Scenario UI 不可用，Action mutation 已关闭。</p></section>
      ) : (
        <section className="surface-card" aria-labelledby="action-command-title">
          <h2 id="action-command-title">业务操作</h2>
          <p className="empty-note">当前 lifecycle 只用于隐藏明显无关操作；服务器授权与并发校验仍是最终结果。</p>
          {action.lifecycle === 'todo' ? (
            <div className="command-stack">
              <button type="button" onClick={() => void runCommand('开始 Action', () => transitionActionItem(action.id, 'start'))} disabled={commandBusy}>开始</button>
              <label>取消原因<input value={transitionReason} onChange={(event) => setTransitionReason(event.target.value)} disabled={commandBusy} /></label>
              <button type="button" className="secondary" onClick={() => void runCommand('取消 Action', () => transitionActionItem(action.id, 'cancel', transitionReason))} disabled={commandBusy}>取消</button>
            </div>
          ) : null}
          {action.lifecycle === 'in_progress' ? (
            <div className="command-stack">
              <button type="button" onClick={() => void runCommand('完成 Action', () => transitionActionItem(action.id, 'complete'))} disabled={commandBusy}>完成</button>
              <label>取消原因<input value={transitionReason} onChange={(event) => setTransitionReason(event.target.value)} disabled={commandBusy} /></label>
              <button type="button" className="secondary" onClick={() => void runCommand('取消 Action', () => transitionActionItem(action.id, 'cancel', transitionReason))} disabled={commandBusy}>取消</button>
            </div>
          ) : null}
          {action.lifecycle === 'done' ? <button type="button" onClick={() => void runCommand('重新打开 Action', () => transitionActionItem(action.id, 'reopen'))} disabled={commandBusy}>重新打开</button> : null}
          {action.lifecycle === 'cancelled' ? <p className="empty-note">当前 Action 已取消，无 Product transition。</p> : null}
          {commandMessage === null ? null : <p role="status">{commandMessage}</p>}
        </section>
      )}

      <section className="surface-card" aria-labelledby="action-nudge-title">
        <h2 id="action-nudge-title">协作提醒</h2>
        <p className="empty-note">按钮不证明催办权限，也不选择接收人；服务器按当前 exact Scenario 与关系事实重新授权并解析 recipient。</p>
        <button
          type="button"
          className="secondary"
          disabled={nudgeBusy}
          onClick={() => void runNudge(action.id)}
        >
          {nudgeBusy ? '正在催办…' : '催一下'}
        </button>
        {nudgeMessage === null ? null : <p role="status">{nudgeMessage}</p>}
      </section>

      <section className="surface-card" aria-labelledby="evidence-title">
        <h2 id="evidence-title">Evidence</h2>
        {evidenceState.status === 'idle' || evidenceState.status === 'loading' ? <p>正在读取 Evidence metadata…</p> : null}
        {evidenceState.status === 'unavailable' ? <p className="empty-note">Evidence 不可用。</p> : null}
        {evidenceState.status === 'error' ? <p role="alert">{evidenceState.message}</p> : null}
        {evidenceState.status === 'ready' && evidenceState.data.length === 0 ? <p className="empty-note">暂无 Evidence metadata。</p> : null}
        {evidenceState.status === 'ready' && evidenceState.data.length > 0 ? (
          <ul className="surface-list">
            {evidenceState.data.map((evidence) => (
              <li key={evidence.id}>
                <strong>{evidence.original_name}</strong>
                <span>{evidence.content_type ?? 'unknown type'} · {formatBytes(evidence.size_bytes)}</span>
                <span>{evidence.description ?? '无说明'}</span>
                <span>上传人 {evidence.uploaded_by} · {formatDateTime(evidence.created_at)}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="empty-note">本阶段不提供 storage key / SHA 输入、二进制上传或下载。</p>
      </section>

      <section className="surface-card" aria-labelledby="action-activity-title">
        <h2 id="action-activity-title">Action Activity</h2>
        {activityState.status === 'idle' || activityState.status === 'loading' ? <p>正在读取 Activity…</p> : null}
        {activityState.status === 'unavailable' ? <p className="empty-note">Activity 不可用。</p> : null}
        {activityState.status === 'error' ? <p role="alert">{activityState.message}</p> : null}
        {activityState.status === 'ready' && activityState.data.length === 0 ? <p className="empty-note">暂无 ActionItem-subject Activity。</p> : null}
        {activityState.status === 'ready' && activityState.data.length > 0 ? (
          <ol className="activity-list">
            {activityState.data.map((activity) => (
              <li key={activity.id}>
                <strong>{activity.event_type}</strong>
                <span>{formatDateTime(activity.occurred_at)}</span>
                <span>Actor {activity.actor_id ?? 'system'}</span>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
    </article>
  )
}