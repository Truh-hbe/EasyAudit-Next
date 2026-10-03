import { NotificationOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Descriptions, Empty, Flex, Result, Spin, Timeline, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

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
import {
  BUSY_FAILURE,
  NOT_AVAILABLE_TEXT,
  classifyCommandFailure,
  failureAlertType,
  failureNeedsRefresh,
} from '../../product/commandFailure'
import type { CommandFailure, CommandResult } from '../../product/commandFailure'
import { formatDateTime } from '../../product/format'
import { participantRoleName, scenarioName, scenarioVersionText, submissionPurposeName } from '../../product/terms'
import { resolveFindingScenarioAdapter } from '../../scenarios'
import type { ScenarioCommandOptions, ScenarioFindingCommandPorts } from '../../scenarios/registry'
import { ActivityEventName } from '../../ui/ActivityEventName'
import { ButtonLink } from '../../ui/ButtonLink'
import { InitialLoading } from '../../ui/InitialLoading'
import { ItemList } from '../../ui/ItemList'
import { PageHeader } from '../../ui/PageHeader'
import { StatusTag } from '../../ui/StatusTag'
import { ActorAssignDrawer, actorKindText } from '../ActorAssignDrawer'
import type { AssignRoleOption } from '../ActorAssignDrawer'
import { actorText } from '../actorNames'
import { SectionNotice } from '../SectionNotice'
import { SectionSpin } from '../SectionSpin'
import { useScopedResource } from '../useScopedResource'
import { ActionCreateDrawer } from './ActionCreateDrawer'
import type { ActionCreateInput } from './ActionCreateDrawer'

const RESPONSIBILITY_ROLES = ['responsible_department', 'owner'] as const

type NudgeNotice =
  | { findingId: string; type: 'success'; text: string }
  | { findingId: string; type: 'failure'; failure: CommandFailure }

export function FindingDetailPage() {
  const { findingId } = useParams()
  const { message } = App.useApp()
  const currentFindingIdRef = useRef(findingId)
  currentFindingIdRef.current = findingId
  const busyRef = useRef(false)
  const nudgeBusyRef = useRef(false)
  const [revision, setRevision] = useState(0)
  const [commandBusy, setCommandBusy] = useState(false)
  const [notice, setNotice] = useState<CommandFailure | null>(null)
  const [nudgeBusy, setNudgeBusy] = useState(false)
  const [nudgeNotice, setNudgeNotice] = useState<NudgeNotice | null>(null)
  const [participantDrawerOpen, setParticipantDrawerOpen] = useState(false)
  const [actionDrawerOpen, setActionDrawerOpen] = useState(false)
  const refresh = () => setRevision((value) => value + 1)

  // 切换发现项时丢弃上一个发现项的弹层、提示与进行中状态。
  useEffect(() => {
    busyRef.current = false
    nudgeBusyRef.current = false
    setCommandBusy(false)
    setNotice(null)
    setNudgeBusy(false)
    setNudgeNotice(null)
    setParticipantDrawerOpen(false)
    setActionDrawerOpen(false)
  }, [findingId])

  const primary = useScopedResource(
    findingId ?? null,
    revision,
    (signal) => getFinding(findingId ?? '', signal),
    '发现项请求失败',
  )
  const finding = primary.status === 'ready' ? primary.data : null
  // 主资源授权通过之后才读取从属资源。
  const scope = finding?.id ?? null
  const caseId = finding?.case_id ?? ''
  const caseState = useScopedResource(scope, revision, (signal) => getReviewCase(caseId, signal), '审查活动请求失败')
  const participants = useScopedResource(
    scope,
    revision,
    (signal) => getFindingParticipantViews(scope ?? '', signal),
    '参与人请求失败',
  )
  const actions = useScopedResource(scope, revision, (signal) => getFindingActions(scope ?? '', signal), '整改项请求失败')
  const submissions = useScopedResource(
    scope,
    revision,
    (signal) => getFindingSubmissions(scope ?? '', signal),
    '提交记录请求失败',
  )
  const activities = useScopedResource(
    scope,
    revision,
    (signal) => getFindingActivities(scope ?? '', signal),
    '操作记录请求失败',
  )

  const participantData = participants.status === 'ready' ? participants.data : null
  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const participant of participantData ?? []) {
      if (participant.actor_kind === 'user') map.set(participant.actor_id, participant.display_name)
    }
    return map
  }, [participantData])

  // targetId 是构造该命令时的发现项：弹层或确认框晚于路由切换残留时，当前页面已不是它，不发请求。
  async function runCommand(
    targetId: string,
    label: string,
    command: () => Promise<unknown>,
    options: ScenarioCommandOptions = {},
  ): Promise<CommandResult> {
    if (currentFindingIdRef.current !== targetId || busyRef.current) return { ok: false, failure: BUSY_FAILURE }
    const commandFindingId = targetId
    busyRef.current = true
    setCommandBusy(true)
    setNotice(null)
    let result: CommandResult
    try {
      await command()
      result = { ok: true }
    } catch (error) {
      result = { ok: false, failure: classifyCommandFailure(error, { label, fields: options.fields }) }
    }
    if (currentFindingIdRef.current !== commandFindingId) return result
    busyRef.current = false
    setCommandBusy(false)
    if (result.ok) {
      void message.success(`已完成：${label}`)
      refresh()
    } else {
      if (options.notify !== false && result.failure.message !== '') setNotice(result.failure)
      // 不自动重放；冲突、权限变化或结果未知时只重新读取，由用户核对后再决定。
      if (failureNeedsRefresh(result.failure)) refresh()
    }
    return result
  }

  async function runNudge(currentFindingId: string) {
    if (currentFindingIdRef.current !== currentFindingId || nudgeBusyRef.current) return
    const commandFindingId = findingId
    nudgeBusyRef.current = true
    setNudgeBusy(true)
    setNudgeNotice(null)
    try {
      const result = await nudgeFinding(currentFindingId)
      if (currentFindingIdRef.current !== commandFindingId) return
      setNudgeNotice({
        findingId: currentFindingId,
        type: 'success',
        text: `服务器已确认催办：已通知 ${result.recipient_count} 人，操作记录 ${result.activity_id}。`,
      })
      refresh()
    } catch (error) {
      if (currentFindingIdRef.current !== commandFindingId) return
      const failure = classifyCommandFailure(error, { label: '催办' })
      setNudgeNotice({ findingId: currentFindingId, type: 'failure', failure })
      if (failureNeedsRefresh(failure)) refresh()
    } finally {
      if (currentFindingIdRef.current === commandFindingId) {
        nudgeBusyRef.current = false
        setNudgeBusy(false)
      }
    }
  }

  if (findingId === undefined || primary.status === 'unavailable') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="发现项" />
        <Card>
          <Result status="404" title={NOT_AVAILABLE_TEXT} extra={<ButtonLink to="/review-cases">返回审查活动列表</ButtonLink>} />
        </Card>
      </Flex>
    )
  }

  if (primary.status === 'loading') {
    return (
      <Flex vertical gap={16} aria-busy="true">
        <PageHeader title="发现项" />
        <Card>
          <InitialLoading label="正在确认访问权限" rows={6} />
        </Card>
      </Flex>
    )
  }

  if (primary.status === 'error') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="发现项" />
        <Alert
          type="error"
          showIcon
          title={primary.message}
          action={
            <Button size="small" onClick={refresh}>
              重新加载
            </Button>
          }
        />
      </Flex>
    )
  }

  if (primary.status !== 'ready' || finding === null) return null

  const caseContext = caseState.status === 'ready' ? caseState.data : null
  const scenarioAdapter =
    caseContext === null
      ? undefined
      : resolveFindingScenarioAdapter(caseContext.scenario_key, caseContext.scenario_version)
  const terminal = finding.lifecycle === 'closed' || finding.lifecycle === 'voided'
  const Interaction = scenarioAdapter?.FindingInteractionSection
  const kindLabel = scenarioAdapter?.findingKindLabel(finding) ?? null
  const interactionCommands: ScenarioFindingCommandPorts = {
    transition: (action, reason) => transitionFinding(finding.id, action, reason ?? null),
    submitRectification: (action, payload) => submitRectification(finding.id, action, payload),
    submitVerification: (action, payload) => submitFindingVerification(finding.id, action, payload),
    reopen: (reason) => reopenFinding(finding.id, reason),
  }
  const participantRoles: AssignRoleOption[] = (scenarioAdapter?.participantOptions ?? []).map((option) => ({
    value: option.roleKey,
    label: option.label,
    actorKind: option.actorKind,
  }))
  const responsibility =
    participants.status !== 'ready'
      ? '读取中'
      : participants.data
          .filter((participant) => (RESPONSIBILITY_ROLES as readonly string[]).includes(participant.role_key))
          .map((participant) => `${participantRoleName(participant.role_key)} ${participant.display_name}`)
          .join('；') || '尚未指定'

  const targetId = finding.id
  const run = (label: string, command: () => Promise<unknown>, options?: ScenarioCommandOptions) =>
    runCommand(targetId, label, command, options)

  async function createAction(input: ActionCreateInput): Promise<CommandResult> {
    return run('新建整改项', () => createActionItem(targetId, input), {
      fields: ['title', 'due_at'],
      notify: false,
    })
  }

  return (
    <Flex component="article" vertical gap={16} aria-labelledby="finding-title">
      <PageHeader
        title={finding.title}
        titleId="finding-title"
        meta={
          <>
            <StatusTag kind="finding" value={finding.lifecycle} />
            <StatusTag kind="severity" value={finding.severity} />
            {caseContext === null ? null : (
              <Typography.Text type="secondary">
                {scenarioName(caseContext.scenario_key)}
                {kindLabel === null ? '' : ` · ${kindLabel}`}
              </Typography.Text>
            )}
          </>
        }
        extra={<ButtonLink to={`/review-cases/${finding.case_id}`}>返回审查活动</ButtonLink>}
      />

      {notice === null || notice.kind === 'session' ? null : (
        <Alert
          type={failureAlertType(notice)}
          showIcon
          title={notice.message}
          closable={{ onClose: () => setNotice(null) }}
        />
      )}
      {primary.refreshError === null ? null : (
        <Alert type="warning" showIcon title={`重新读取失败，当前显示的可能不是最新内容：${primary.refreshError}`} />
      )}

      <Flex vertical gap={16}>
          {caseState.status === 'loading' ? (
            <Card>
              <InitialLoading label="正在加载审查场景" rows={1} />
            </Card>
          ) : null}
          {caseState.status === 'unavailable' || caseState.status === 'error' ? (
            <Alert type="warning" showIcon title="审查场景信息不可用，场景相关的编辑已关闭。" />
          ) : null}
          {caseContext !== null && scenarioAdapter === undefined ? (
            <Alert
              type="warning"
              showIcon
              role="status"
              title={`暂不支持当前版本的审查场景界面（${scenarioName(caseContext.scenario_key)} · ${scenarioVersionText(caseContext.scenario_key, caseContext.scenario_version)}）。仍可查看发现项的通用信息。`}
            />
          ) : null}
          {Interaction === undefined ? null : (
            <Interaction key={finding.id} finding={finding} disabled={commandBusy} commands={interactionCommands} execute={run} />
          )}

          <section aria-labelledby="finding-overview-title">
            <Card title={<h2 id="finding-overview-title">概览</h2>}>
              <Spin spinning={primary.refreshing} description="正在刷新">
              <Descriptions
                column={{ xs: 1, md: 2 }}
                items={[
                  { key: 'responsibility', label: '责任方', children: responsibility },
                  {
                    key: 'scenario',
                    label: '场景类型',
                    children:
                      caseContext === null
                        ? '—'
                        : `${scenarioName(caseContext.scenario_key)} · ${scenarioVersionText(caseContext.scenario_key, caseContext.scenario_version)}`,
                  },
                  ...(scenarioAdapter?.findingScenarioItems(finding) ?? []).map((item) => ({
                    key: item.key,
                    label: item.label,
                    children: item.value,
                  })),
                  { key: 'raised_at', label: '提出时间', children: formatDateTime(finding.raised_at) },
                  { key: 'raised_by', label: '提出人', children: actorText(finding.raised_by, names) },
                  { key: 'description', label: '描述', span: { xs: 1, md: 2 }, children: finding.description ?? '—' },
                  { key: 'id', label: '发现项 ID', children: finding.id },
                  {
                    key: 'case',
                    label: '审查活动',
                    children: <Link to={`/review-cases/${finding.case_id}`}>{caseContext?.title ?? finding.case_id}</Link>,
                  },
                ]}
              />
              </Spin>
            </Card>
          </section>

          <section aria-labelledby="participants-title">
            <Card
              title={<h2 id="participants-title">参与方</h2>}
              extra={
                scenarioAdapter !== undefined && !terminal ? (
                  <Button icon={<PlusOutlined aria-hidden />} onClick={() => setParticipantDrawerOpen(true)}>
                    添加参与人
                  </Button>
                ) : null
              }
            >
<SectionSpin state={participants}>
              <SectionNotice state={participants} loadingLabel="正在读取参与方" unavailableText="参与关系不可用。" />
              {participants.status === 'ready' ? (
                <ItemList
                  label="参与方"
                  emptyText="暂无参与关系。"
                  items={participants.data.map((participant) => ({
                    key: `${participant.actor_kind}-${participant.actor_id}-${participant.role_key}`,
                    content: (
                      <Flex vertical>
                        <Typography.Text strong>{participant.display_name}</Typography.Text>
                        <Typography.Text type="secondary">
                          {participantRoleName(participant.role_key)} · {actorKindText(participant.actor_kind)} · 加入于{' '}
                          {formatDateTime(participant.assigned_at)}
                        </Typography.Text>
                      </Flex>
                    ),
                  }))}
                />
              ) : null}
</SectionSpin>
            </Card>
          </section>

          <section aria-labelledby="actions-title">
            <Card
              title={<h2 id="actions-title">整改项</h2>}
              extra={
                scenarioAdapter !== undefined && finding.lifecycle === 'rectifying' ? (
                  <Button icon={<PlusOutlined aria-hidden />} onClick={() => setActionDrawerOpen(true)}>
                    新建整改项
                  </Button>
                ) : null
              }
            >
<SectionSpin state={actions}>
              <SectionNotice state={actions} loadingLabel="正在读取整改项" unavailableText="整改项不可用。" />
              {actions.status === 'ready' ? (
                <ItemList
                  label="整改项"
                  emptyText="暂无整改项。"
                  items={actions.data.map((action) => ({
                    key: action.id,
                    content: (
                      <Flex justify="space-between" align="center" wrap gap={8}>
                        <Flex vertical gap={4}>
                          <Link to={`/action-items/${action.id}`}>{action.title}</Link>
                          <Typography.Text type="secondary">
                            到期 {formatDateTime(action.due_at)} · 完成于 {formatDateTime(action.completed_at)}
                          </Typography.Text>
                        </Flex>
                        <StatusTag kind="actionItem" value={action.lifecycle} />
                      </Flex>
                    ),
                  }))}
                />
              ) : null}
</SectionSpin>
            </Card>
          </section>

          <section aria-labelledby="finding-nudge-title">
            <Card title={<h2 id="finding-nudge-title">协作提醒</h2>}>
              <Flex vertical gap={12} align="flex-start">
                <Typography.Text type="secondary">
                  按钮不代表有催办权限，也不选择被催办的人；服务器会按当前审查场景和相关人员重新授权并确定对象。
                </Typography.Text>
                <Button
                  icon={<NotificationOutlined aria-hidden />}
                  loading={nudgeBusy}
                  onClick={() => void runNudge(finding.id)}
                >
                  催办
                </Button>
                {nudgeNotice === null || nudgeNotice.findingId !== finding.id ? null : nudgeNotice.type === 'success' ? (
                  <Alert type="success" showIcon title={nudgeNotice.text} />
                ) : nudgeNotice.failure.message === '' ? null : (
                  <Alert type={failureAlertType(nudgeNotice.failure)} showIcon title={nudgeNotice.failure.message} />
                )}
              </Flex>
            </Card>
          </section>

          <section aria-labelledby="submission-history-title">
            <Card title={<h2 id="submission-history-title">提交记录</h2>}>
              <SectionSpin state={submissions}>
              <Flex vertical gap={12}>
                <SectionNotice state={submissions} loadingLabel="正在读取提交记录" unavailableText="提交记录不可用。" />
                {submissions.status === 'ready' ? (
                  <ItemList
                    label="提交记录"
                    emptyText="暂无提交记录。"
                    items={submissions.data.map((submission) => ({
                      key: submission.id,
                      content: (
                        <Flex vertical>
                          <Typography.Text strong>{submissionPurposeName(submission.purpose)}</Typography.Text>
                          <Typography.Text type="secondary">
                            {formatDateTime(submission.submitted_at)} · 提交人 {actorText(submission.submitted_by, names)}
                          </Typography.Text>
                        </Flex>
                      ),
                    }))}
                  />
                ) : null}
                <Typography.Text type="secondary">历史提交内容不用于推断当前状态或权限。</Typography.Text>
              </Flex>
              </SectionSpin>
            </Card>
          </section>

          <section aria-labelledby="finding-activity-title">
            <Card title={<h2 id="finding-activity-title">操作记录</h2>}>
              <SectionSpin state={activities}>
              <SectionNotice state={activities} loadingLabel="正在读取操作记录" unavailableText="操作记录不可用。" />
              {activities.status === 'ready' && activities.data.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无操作记录。" />
              ) : null}
              {activities.status === 'ready' && activities.data.length > 0 ? (
                <Timeline
                  items={activities.data.map((activity) => ({
                    key: activity.id,
                    content: (
                      <Flex vertical gap={4}>
                        <ActivityEventName eventType={activity.event_type} />
                        <Typography.Text type="secondary">
                          {formatDateTime(activity.occurred_at)} · 操作人 {actorText(activity.actor_id, names)}
                        </Typography.Text>
                      </Flex>
                    ),
                  }))}
                />
              ) : null}
              </SectionSpin>
            </Card>
          </section>
      </Flex>

      {scenarioAdapter === undefined ? null : (
        <>
          <ActorAssignDrawer
            open={participantDrawerOpen}
            onClose={() => setParticipantDrawerOpen(false)}
            scopeKey={finding.id}
            title="添加参与人"
            roleFieldLabel="关系角色"
            actorFieldLabel="参与人"
            okText="添加参与人"
            roles={participantRoles}
            search={(role, query, signal) =>
              searchFindingParticipantCandidates(finding.id, role.value, role.actorKind, query, signal)
            }
            add={(role, candidate) =>
              run(
                '添加参与人',
                () => addFindingParticipant(finding.id, candidate.actor_kind, candidate.actor_id, role.value),
                { notify: false },
              )
            }
            onAccessLost={refresh}
          />
          <ActionCreateDrawer open={actionDrawerOpen} onClose={() => setActionDrawerOpen(false)} create={createAction} />
        </>
      )}
    </Flex>
  )
}
