import { Alert, Button, Card, Descriptions, Empty, Flex, Result, Timeline, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
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
import { useSession } from '../../app/auth/session'
import { formatDateTime } from '../../product/format'
import { caseRoleName, scenarioName, scenarioVersionText } from '../../product/terms'
import { ActivityEventName } from '../../ui/ActivityEventName'
import { ButtonLink } from '../../ui/ButtonLink'
import { InitialLoading } from '../../ui/InitialLoading'
import { ItemList } from '../../ui/ItemList'
import { PageHeader } from '../../ui/PageHeader'
import { isDeadlineStatus, StatusTag } from '../../ui/StatusTag'
import { resolveCaseScenarioAdapter } from '../../scenarios'
import { FindingCreatePanel } from '../findings/FindingCreatePanel'
import { initialCaseAuthorization, reduceCaseAuthorization } from './caseAuthorization'
import type { CaseAuthorizationEvent, CaseAuthorizationState } from './caseAuthorization'
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

function SectionNotice({ state, loadingLabel, unavailableText }: {
  state: SectionState<unknown>
  loadingLabel: string
  unavailableText: string
}) {
  if (state.status === 'loading' || state.status === 'idle') return <InitialLoading label={loadingLabel} rows={2} />
  if (state.status === 'unavailable') return <Typography.Text type="secondary">{unavailableText}</Typography.Text>
  if (state.status === 'error') return <Alert type="error" showIcon title={state.message} />
  return null
}

function FindingSection({ state }: { state: SectionState<FindingResponse[]> }) {
  return (
    <section aria-labelledby="findings-title">
      <Card title={<h2 id="findings-title">发现项</h2>}>
        <SectionNotice state={state} loadingLabel="正在读取发现项" unavailableText="发现项列表不可用。" />
        {state.status === 'ready' ? (
          <ItemList
            label="发现项"
            emptyText="暂无可见的发现项。"
            items={state.data.map((finding) => ({
              key: finding.id,
              content: (
                <Flex justify="space-between" align="center" wrap gap={8}>
                  <Flex vertical gap={4}>
                    <Link to={`/findings/${finding.id}`}>{finding.title}</Link>
                    <Typography.Text type="secondary">提出于 {formatDateTime(finding.raised_at)}</Typography.Text>
                  </Flex>
                  <Flex align="center" wrap gap={8}>
                    <StatusTag kind="severity" value={finding.severity} />
                    <StatusTag kind="finding" value={finding.lifecycle} />
                  </Flex>
                </Flex>
              ),
            }))}
          />
        ) : null}
      </Card>
    </section>
  )
}

// 操作人名称只取自已授权的成员接口；找不到时显示“名称暂不可用”和短 ID。
function actorText(actorId: string | null, members: readonly CaseMemberViewResponse[]): string {
  if (actorId === null) return '系统'
  const member = members.find((candidate) => candidate.user_id === actorId)
  return member === undefined ? `名称暂不可用（${actorId.slice(0, 8)}）` : member.display_name
}

function ActivitySection({ state, members }: {
  state: SectionState<ReviewCaseActivityResponse[]>
  members: readonly CaseMemberViewResponse[]
}) {
  return (
    <section aria-labelledby="activity-title">
      <Card title={<h2 id="activity-title">操作记录</h2>}>
        <SectionNotice state={state} loadingLabel="正在读取操作记录" unavailableText="操作记录不可用。" />
        {state.status === 'ready' && state.data.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无操作记录。" />
        ) : null}
        {state.status === 'ready' && state.data.length > 0 ? (
          <Timeline
            items={state.data.map((activity) => ({
              key: activity.id,
              content: (
                <Flex vertical gap={4}>
                  <ActivityEventName eventType={activity.event_type} />
                  <Typography.Text type="secondary">
                    {formatDateTime(activity.occurred_at)} · 操作人 {actorText(activity.actor_id, members)}
                  </Typography.Text>
                </Flex>
              ),
            }))}
          />
        ) : null}
      </Card>
    </section>
  )
}

function ManagementProgressSection({ state }: { state: SectionState<ManagementCaseProgressResponse> }) {
  return (
    <section aria-labelledby="management-progress-title">
      <Card title={<h2 id="management-progress-title">管理进度</h2>}>
        <SectionNotice
          state={state}
          loadingLabel="正在确认管理进度可见性"
          unavailableText="当前用户没有可用的管理进度摘要。"
        />
        {state.status === 'ready' ? (
          <Descriptions
            column={{ xs: 1, md: 2 }}
            items={[
              {
                key: 'deadline',
                label: '截止状态',
                children: isDeadlineStatus(state.data.case.deadline_bucket)
                  ? <StatusTag kind="deadline" value={state.data.case.deadline_bucket} />
                  : '未临近截止',
              },
              { key: 'findings', label: '发现项', children: state.data.case.findings.total },
              {
                key: 'finding-states',
                label: '待处理 / 整改中 / 待验证',
                children: `${state.data.case.findings.open} / ${state.data.case.findings.rectifying} / ${state.data.case.findings.verifying}`,
              },
              { key: 'actions', label: '整改项', children: state.data.case.actions.total },
              { key: 'overdue', label: '整改项已逾期', children: state.data.case.actions.overdue },
              { key: 'due-soon', label: '整改项即将到期', children: state.data.case.actions.due_soon },
            ]}
          />
        ) : null}
      </Card>
    </section>
  )
}

function roleLabel(roleKey: string, options: readonly { roleKey: string; label: string }[] | undefined): string {
  return options?.find((option) => option.roleKey === roleKey)?.label ?? caseRoleName(roleKey)
}

type SetPrimary = (update: (current: PrimaryState) => PrimaryState) => void

// 主授权状态机（./caseAuthorization.ts）的执行器：持有当前状态，执行 reducer 返回的指令。
function createAuthorizationController(setPrimary: SetPrimary) {
  let state: CaseAuthorizationState = initialCaseAuthorization

  function dispatch(event: CaseAuthorizationEvent, caseId: string): void {
    const result = reduceCaseAuthorization(state, event)
    state = result.state
    for (const effect of result.effects) {
      if (effect === 'remove-protected') {
        setPrimary((current) => (current.caseId === caseId ? { status: 'unavailable', caseId } : current))
      } else {
        recheck(caseId, state.generation)
      }
    }
  }

  // 静默主读取：不进入加载态，不卸载页面；失败（500/网络）保持现有内容。
  function recheck(caseId: string, generation: number): void {
    void getReviewCase(caseId).then(
      (data) => {
        if (state.generation !== generation) return
        dispatch({ type: 'response', generation, result: 'ok' }, caseId)
        if (state.status === 'authorized') {
          setPrimary((current) =>
            current.status === 'ready' && current.caseId === caseId ? { status: 'ready', caseId, data } : current,
          )
        }
      },
      (error: unknown) => {
        dispatch({ type: 'response', generation, result: unavailable(error) ? 'denied' : 'error' }, caseId)
      },
    )
  }

  return {
    load: (): number => {
      state = reduceCaseAuthorization(state, { type: 'load' }).state
      return state.generation
    },
    generation: (): number => state.generation,
    isCurrent: (generation: number): boolean => state.generation === generation,
    status: () => state.status,
    respond: (generation: number, caseId: string, result: 'ok' | 'denied' | 'error'): void =>
      dispatch({ type: 'response', generation, result }, caseId),
    trigger: (generation: number, caseId: string): void =>
      dispatch({ type: 'trigger', generation }, caseId),
  }
}

export function ReviewCaseDetailPage() {
  const { caseId } = useParams()
  const { state: sessionState } = useSession()
  const [revision, setRevision] = useState(0)
  const [teamRevision, setTeamRevision] = useState(0)
  const [primary, setPrimary] = useState<PrimaryState>({ status: 'loading', caseId: undefined })
  const [members, setMembers] = useState<SectionState<CaseMemberViewResponse[]>>(idleSection)
  const [findings, setFindings] = useState<SectionState<FindingResponse[]>>(idleSection)
  const [activities, setActivities] = useState<SectionState<ReviewCaseActivityResponse[]>>(idleSection)
  const [management, setManagement] = useState<SectionState<ManagementCaseProgressResponse>>(idleSection)
  const authorization = useMemo(() => createAuthorizationController(setPrimary), [])

  useEffect(() => {
    const loadGeneration = authorization.load()
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
        if (controller.signal.aborted) return
        authorization.respond(loadGeneration, requestedCaseId, 'ok')
        if (authorization.isCurrent(loadGeneration) && authorization.status() === 'authorized') {
          setPrimary({ status: 'ready', caseId: requestedCaseId, data })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (unavailable(error)) {
          // 状态机发出 remove-protected，把该活动置为不可用。
          authorization.respond(loadGeneration, requestedCaseId, 'denied')
          return
        }
        authorization.respond(loadGeneration, requestedCaseId, 'error')
        setPrimary({
          status: 'error',
          caseId: requestedCaseId,
          message: sectionMessage(error, '审查活动请求失败'),
        })
      })
    return () => controller.abort()
  }, [authorization, caseId, revision])

  const primaryMatchesRoute = primary.caseId === caseId
  const authorizedCaseId =
    primaryMatchesRoute && primary.status === 'ready' ? primary.data.id : null
  useEffect(() => {
    if (authorizedCaseId === null) return
    const controller = new AbortController()
    const generation = authorization.generation()
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
        // 与主授权同语义的从属读取被拒（403/404）：重新确认主授权，不论是不是第一次。
        if (unavailable(error)) authorization.trigger(generation, authorizedCaseId)
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
        // 与主授权同语义的从属读取被拒（403/404）：重新确认主授权，不论是不是第一次。
        if (unavailable(error)) authorization.trigger(generation, authorizedCaseId)
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
  }, [authorization, authorizedCaseId, teamRevision])

  useEffect(() => {
    if (authorizedCaseId === null) return
    const controller = new AbortController()
    const generation = authorization.generation()
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
        // 与主授权同语义的从属读取被拒（403/404）：重新确认主授权，不论是不是第一次。
        if (unavailable(error)) authorization.trigger(generation, authorizedCaseId)
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
        // 管理进度的 403/404 是额外的权限边界（非管理者的常态），只显示不可用，永不触发主授权重读。
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
  }, [authorization, authorizedCaseId])

  if (!primaryMatchesRoute || primary.status === 'loading') {
    return (
      <Flex vertical gap={16} aria-busy="true">
        <PageHeader title="审查活动" />
        <Card><InitialLoading label="正在确认访问权限" rows={6} /></Card>
      </Flex>
    )
  }

  if (primary.status === 'unavailable') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="审查活动" />
        <Card>
          <Result
            status="404"
            title="内容不存在或无权访问"
            extra={<ButtonLink to="/review-cases">返回审查活动列表</ButtonLink>}
          />
        </Card>
      </Flex>
    )
  }

  if (primary.status === 'error') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="审查活动" />
        <Alert
          type="error"
          showIcon
          title={primary.message}
          action={<Button size="small" onClick={() => setRevision((value) => value + 1)}>重新加载</Button>}
        />
      </Flex>
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
  const currentUserId = sessionState.status === 'authenticated' ? sessionState.user.id : null
  const myRoles = memberData
    .filter((member) => member.user_id === currentUserId)
    .map((member) => roleLabel(member.role_key, scenarioAdapter?.caseMemberRoleOptions))
  const hasSchedule = reviewCase.planned_start_at !== null || reviewCase.planned_end_at !== null
  const secondary = (text: string) => <Typography.Text type="secondary">{text}</Typography.Text>

  return (
    <Flex component="article" vertical gap={16} aria-labelledby="case-title">
      <PageHeader
        title={reviewCase.title}
        titleId="case-title"
        meta={
          <>
            <StatusTag kind="reviewCase" value={reviewCase.lifecycle} />
            {secondary(scenarioName(reviewCase.scenario_key))}
            {hasSchedule
              ? secondary(`计划 ${formatDateTime(reviewCase.planned_start_at)} – ${formatDateTime(reviewCase.planned_end_at)}`)
              : null}
            {myRoles.length > 0 ? secondary(`我的角色 ${myRoles.join('、')}`) : null}
            {managementState.status === 'ready' ? secondary(`数据时间 ${formatDateTime(managementState.data.as_of)}`) : null}
          </>
        }
      />

      <section aria-labelledby="overview-title">
        <Card title={<h2 id="overview-title">概览</h2>}>
          <Descriptions
            column={{ xs: 1, md: 2 }}
            items={[
              { key: 'id', label: '审查活动 ID', children: reviewCase.id },
              { key: 'version', label: '场景版本', children: scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version) },
              { key: 'plan', label: '审查计划', children: reviewCase.plan_id ?? '—' },
              { key: 'planned-start', label: '计划开始', children: formatDateTime(reviewCase.planned_start_at) },
              { key: 'planned-end', label: '计划结束', children: formatDateTime(reviewCase.planned_end_at) },
              { key: 'started', label: '实际开始', children: formatDateTime(reviewCase.started_at) },
              { key: 'fieldwork', label: '现场完成', children: formatDateTime(reviewCase.fieldwork_completed_at) },
              { key: 'closed', label: '关闭', children: formatDateTime(reviewCase.closed_at) },
              { key: 'created', label: '创建', children: formatDateTime(reviewCase.created_at) },
            ]}
          />
        </Card>
      </section>

      {/* 场景适配器和发现项入口仍是遗留样式（场景适配器与发现项详情共用），放在遗留容器内，随 UI-5 迁移。 */}
      {ScenarioSection === undefined ? (
        <section aria-labelledby="scenario-unsupported-title">
          <Card title={<h2 id="scenario-unsupported-title">审查场景</h2>}>
            <Alert
              type="warning"
              showIcon
              role="status"
              title={`暂不支持当前版本的审查场景界面（${scenarioName(reviewCase.scenario_key)} · ${scenarioVersionText(reviewCase.scenario_key, reviewCase.scenario_version)}）。仍可查看审查活动的通用信息。`}
            />
          </Card>
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
        onTeamChanged={() => {
          setTeamRevision((value) => value + 1)
          authorization.trigger(authorization.generation(), reviewCase.id)
        }}
        onAccessLost={() => setRevision((value) => value + 1)}
      />
      <ActivitySection state={activityState} members={memberData} />
    </Flex>
  )
}
