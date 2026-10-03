import { CheckOutlined, NotificationOutlined, PlayCircleOutlined, PlusOutlined, RollbackOutlined, StopOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Descriptions, Empty, Flex, Result, Spin, Timeline, Typography } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

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
import {
  BUSY_FAILURE,
  NOT_AVAILABLE_TEXT,
  classifyCommandFailure,
  failureAlertType,
  failureNeedsRefresh,
} from '../../product/commandFailure'
import type { CommandFailure, CommandResult } from '../../product/commandFailure'
import { formatDateTime } from '../../product/format'
import { assignmentRoleName } from '../../product/terms'
import { resolveFindingScenarioAdapter } from '../../scenarios'
import { ActivityEventName } from '../../ui/ActivityEventName'
import { ButtonLink } from '../../ui/ButtonLink'
import { CommandTextDialog } from '../../ui/CommandTextDialog'
import { InitialLoading } from '../../ui/InitialLoading'
import { useConfirm } from '../../ui/useConfirm'
import { ItemList } from '../../ui/ItemList'
import { PageHeader } from '../../ui/PageHeader'
import { StatusTag } from '../../ui/StatusTag'
import { ActorAssignDrawer } from '../ActorAssignDrawer'
import type { AssignRoleOption } from '../ActorAssignDrawer'
import { actorText } from '../actorNames'
import { SectionNotice } from '../SectionNotice'
import { SectionSpin } from '../SectionSpin'
import { useScopedResource } from '../useScopedResource'
import { EvidenceSection } from './EvidenceSection'

type NudgeNotice =
  | { actionItemId: string; type: 'success'; text: string }
  | { actionItemId: string; type: 'failure'; failure: CommandFailure }

// 完成要求只陈述领域规则（domain.md），不由本页推导新的逾期或完成规则。
function completionRequirement(lifecycle: string, completedAt: string | null): string {
  if (lifecycle === 'done') return `已于 ${formatDateTime(completedAt)} 完成。`
  if (lifecycle === 'cancelled') return '整改项已取消，无需完成。'
  return '完成整改并可上传证据；发现项提交验证前，所有未取消的整改项都必须已完成。'
}

export function ActionItemDetailPage() {
  const { actionItemId } = useParams()
  const { message } = App.useApp()
  const currentActionItemIdRef = useRef(actionItemId)
  currentActionItemIdRef.current = actionItemId
  const busyRef = useRef(false)
  const nudgeBusyRef = useRef(false)
  const [revision, setRevision] = useState(0)
  const [commandBusy, setCommandBusy] = useState(false)
  const [notice, setNotice] = useState<CommandFailure | null>(null)
  const [nudgeBusy, setNudgeBusy] = useState(false)
  const [nudgeNotice, setNudgeNotice] = useState<NudgeNotice | null>(null)
  const [assignDrawerOpen, setAssignDrawerOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const refresh = () => setRevision((value) => value + 1)
  const { confirm, destroy: destroyConfirm } = useConfirm()

  // 切换整改项时丢弃上一个整改项的弹层、提示与进行中状态。
  useEffect(() => {
    busyRef.current = false
    nudgeBusyRef.current = false
    setCommandBusy(false)
    setNotice(null)
    setNudgeBusy(false)
    setNudgeNotice(null)
    setAssignDrawerOpen(false)
    setCancelOpen(false)
    destroyConfirm()
  }, [actionItemId, destroyConfirm])

  const primary = useScopedResource(
    actionItemId ?? null,
    revision,
    (signal) => getActionItem(actionItemId ?? '', signal),
    '整改项请求失败',
  )
  const action = primary.status === 'ready' ? primary.data : null
  // 主资源授权通过之后才读取从属资源。
  const scope = action?.id ?? null
  const findingId = action?.finding_id ?? ''
  const findingState = useScopedResource(scope, revision, (signal) => getFinding(findingId, signal), '发现项请求失败')
  const findingData = findingState.status === 'ready' ? findingState.data : null
  const caseId = findingData?.case_id ?? null
  const caseState = useScopedResource(
    caseId === null ? null : scope,
    revision,
    (signal) => getReviewCase(caseId ?? '', signal),
    '审查活动请求失败',
  )
  const assignees = useScopedResource(scope, revision, (signal) => getActionAssigneeViews(scope ?? '', signal), '执行人请求失败')
  const evidences = useScopedResource(scope, revision, (signal) => getActionEvidences(scope ?? '', signal), '证据请求失败')
  const activities = useScopedResource(
    scope,
    revision,
    (signal) => getActionItemActivities(scope ?? '', signal),
    '操作记录请求失败',
  )

  const assigneeData = assignees.status === 'ready' ? assignees.data : null
  const names = useMemo(() => {
    const map = new Map<string, string>()
    for (const assignee of assigneeData ?? []) {
      if (assignee.actor_kind === 'user') map.set(assignee.actor_id, assignee.display_name)
    }
    return map
  }, [assigneeData])

  // targetId 是构造该命令时的整改项：弹层或确认框晚于路由切换残留时，当前页面已不是它，不发请求。
  async function runCommand(
    targetId: string,
    label: string,
    command: () => Promise<unknown>,
    options: { fields?: readonly string[]; notify?: boolean } = {},
  ): Promise<CommandResult> {
    if (currentActionItemIdRef.current !== targetId || busyRef.current) return { ok: false, failure: BUSY_FAILURE }
    const commandActionItemId = targetId
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
    if (currentActionItemIdRef.current !== commandActionItemId) return result
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

  async function runNudge(currentActionId: string) {
    if (currentActionItemIdRef.current !== currentActionId || nudgeBusyRef.current) return
    const commandActionItemId = actionItemId
    nudgeBusyRef.current = true
    setNudgeBusy(true)
    setNudgeNotice(null)
    try {
      const result = await nudgeActionItem(currentActionId)
      if (currentActionItemIdRef.current !== commandActionItemId) return
      setNudgeNotice({
        actionItemId: currentActionId,
        type: 'success',
        text: `服务器已确认催办：已通知 ${result.recipient_count} 人，操作记录 ${result.activity_id}。`,
      })
      refresh()
    } catch (error) {
      if (currentActionItemIdRef.current !== commandActionItemId) return
      const failure = classifyCommandFailure(error, { label: '催办' })
      setNudgeNotice({ actionItemId: currentActionId, type: 'failure', failure })
      if (failureNeedsRefresh(failure)) refresh()
    } finally {
      if (currentActionItemIdRef.current === commandActionItemId) {
        nudgeBusyRef.current = false
        setNudgeBusy(false)
      }
    }
  }

  if (actionItemId === undefined || primary.status === 'unavailable') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="整改项" />
        <Card>
          <Result status="404" title={NOT_AVAILABLE_TEXT} extra={<ButtonLink to="/review-cases">返回审查活动列表</ButtonLink>} />
        </Card>
      </Flex>
    )
  }

  if (primary.status === 'loading') {
    return (
      <Flex vertical gap={16} aria-busy="true">
        <PageHeader title="整改项" />
        <Card>
          <InitialLoading label="正在确认访问权限" rows={6} />
        </Card>
      </Flex>
    )
  }

  if (primary.status === 'error') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="整改项" />
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

  if (primary.status !== 'ready' || action === null) return null

  const caseContext = caseState.status === 'ready' ? caseState.data : null
  const scenarioAdapter =
    caseContext === null
      ? undefined
      : resolveFindingScenarioAdapter(caseContext.scenario_key, caseContext.scenario_version)
  const assigneeRoles: AssignRoleOption[] = (scenarioAdapter?.assigneeOptions ?? []).map((option) => ({
    value: option.role,
    label: option.label,
    actorKind: option.actorKind,
  }))
  const cancelled = action.lifecycle === 'cancelled'
  const refreshingOf = (state: { status: string; refreshing?: boolean }) => state.status === 'ready' && state.refreshing === true
  const overviewRefreshing = primary.refreshing || refreshingOf(assignees) || refreshingOf(findingState)
  const run = (label: string, command: () => Promise<unknown>, options?: { fields?: readonly string[]; notify?: boolean }) =>
    runCommand(action.id, label, command, options)

  return (
    <Flex component="article" vertical gap={16} aria-labelledby="action-title">
      <PageHeader
        title={action.title}
        titleId="action-title"
        meta={<StatusTag kind="actionItem" value={action.lifecycle} />}
        extra={<ButtonLink to={`/findings/${action.finding_id}`}>返回发现项</ButtonLink>}
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
          <section aria-labelledby="action-overview-title">
            <Card
              title={<h2 id="action-overview-title">整改事项</h2>}
              extra={
                scenarioAdapter !== undefined && !cancelled ? (
                  <Button icon={<PlusOutlined aria-hidden />} onClick={() => setAssignDrawerOpen(true)}>
                    添加执行人
                  </Button>
                ) : null
              }
            >
              <Spin spinning={overviewRefreshing} description="正在刷新">
              <Descriptions
                column={{ xs: 1, md: 2 }}
                items={[
                  { key: 'title', label: '任务', children: action.title },
                  {
                    key: 'assignees',
                    label: '执行人',
                    children:
                      assignees.status === 'ready' ? (
                        <ItemList
                          label="执行人"
                          emptyText="暂无执行人。"
                          items={assignees.data.map((assignee) => ({
                            key: `${assignee.actor_kind}-${assignee.actor_id}-${assignee.role}`,
                            content: (
                              <>
                                <Typography.Text strong>{assignee.display_name}</Typography.Text>
                                <Typography.Text type="secondary">
                                  {' '}
                                  · {assignmentRoleName(assignee.role)} · 加入于 {formatDateTime(assignee.assigned_at)}
                                </Typography.Text>
                              </>
                            ),
                          }))}
                        />
                      ) : (
                        <SectionNotice state={assignees} loadingLabel="正在读取执行人" unavailableText="执行关系不可用。" />
                      ),
                  },
                  { key: 'due', label: '截止时间', children: formatDateTime(action.due_at) },
                  { key: 'requirement', label: '完成要求', children: completionRequirement(action.lifecycle, action.completed_at) },
                  { key: 'completed', label: '完成时间', children: formatDateTime(action.completed_at) },
                  {
                    key: 'finding',
                    label: '所属发现项',
                    children:
                      findingState.status === 'ready' ? (
                        <Flex align="center" wrap gap={8}>
                          <Link to={`/findings/${findingState.data.id}`}>{findingState.data.title}</Link>
                          <StatusTag kind="finding" value={findingState.data.lifecycle} />
                        </Flex>
                      ) : (
                        <SectionNotice state={findingState} loadingLabel="正在读取发现项" unavailableText="发现项信息不可用。" />
                      ),
                  },
                  { key: 'id', label: '整改项 ID', children: action.id },
                ]}
              />
              </Spin>
              <Typography.Text type="secondary">截止时间以服务器记录为准；本页不计算新的逾期规则。</Typography.Text>
            </Card>
          </section>

          <section aria-labelledby="action-command-title">
            <Card title={<h2 id="action-command-title">执行操作</h2>}>
              <Flex vertical gap={12}>
                {scenarioAdapter === undefined ? (
                  <Typography.Text type="secondary">
                    {caseState.status === 'loading' ? '正在确认审查场景…' : '当前审查场景的界面不可用，整改项操作已关闭。'}
                  </Typography.Text>
                ) : (
                  <>
                    <Typography.Text type="secondary">
                      这里只隐藏明显无关的操作；最终授权与并发校验以服务器为准。
                    </Typography.Text>
                    <Flex wrap gap={8}>
                      {action.lifecycle === 'todo' ? (
                        <Button
                          type="primary"
                          icon={<PlayCircleOutlined aria-hidden />}
                          disabled={commandBusy}
                          onClick={() => void run('开始整改项', () => transitionActionItem(action.id, 'start'))}
                        >
                          开始整改项
                        </Button>
                      ) : null}
                      {action.lifecycle === 'in_progress' ? (
                        <Button
                          type="primary"
                          icon={<CheckOutlined aria-hidden />}
                          disabled={commandBusy}
                          onClick={() => void run('完成整改项', () => transitionActionItem(action.id, 'complete'))}
                        >
                          完成整改项
                        </Button>
                      ) : null}
                      {action.lifecycle === 'done' ? (
                        <Button
                          icon={<RollbackOutlined aria-hidden />}
                          disabled={commandBusy}
                          onClick={() =>
                            confirm({
                              title: '重新打开整改项',
                              content: '重新打开后整改项回到执行中，已完成状态与完成时间将被清除，需要重新完成。',
                              okText: '确认重新打开',
                              cancelText: '取消',
                              onOk: async () => {
                                await run('重新打开整改项', () => transitionActionItem(action.id, 'reopen'))
                              },
                            })
                          }
                        >
                          重新打开整改项
                        </Button>
                      ) : null}
                      {action.lifecycle === 'todo' || action.lifecycle === 'in_progress' ? (
                        <Button danger icon={<StopOutlined aria-hidden />} disabled={commandBusy} onClick={() => setCancelOpen(true)}>
                          取消整改项
                        </Button>
                      ) : null}
                    </Flex>
                    {cancelled ? <Typography.Text type="secondary">当前整改项已取消，没有可执行的操作。</Typography.Text> : null}
                  </>
                )}
              </Flex>
            </Card>
          </section>

          <EvidenceSection
            key={action.id}
            actionId={action.id}
            cancelled={cancelled}
            state={evidences}
            names={names}
            onRefresh={refresh}
          />

          <section aria-labelledby="action-nudge-title">
            <Card title={<h2 id="action-nudge-title">协作提醒</h2>}>
              <Flex vertical gap={12} align="flex-start">
                <Typography.Text type="secondary">
                  按钮不代表有催办权限，也不选择被催办的人；服务器会按当前审查场景和相关人员重新授权并确定对象。
                </Typography.Text>
                <Button icon={<NotificationOutlined aria-hidden />} loading={nudgeBusy} onClick={() => void runNudge(action.id)}>
                  催办
                </Button>
                {nudgeNotice === null || nudgeNotice.actionItemId !== action.id ? null : nudgeNotice.type === 'success' ? (
                  <Alert type="success" showIcon title={nudgeNotice.text} />
                ) : nudgeNotice.failure.message === '' ? null : (
                  <Alert type={failureAlertType(nudgeNotice.failure)} showIcon title={nudgeNotice.failure.message} />
                )}
              </Flex>
            </Card>
          </section>

          <section aria-labelledby="action-activity-title">
            <Card title={<h2 id="action-activity-title">操作记录</h2>}>
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
            open={assignDrawerOpen}
            onClose={() => setAssignDrawerOpen(false)}
            scopeKey={action.id}
            title="添加执行人"
            roleFieldLabel="执行角色"
            actorFieldLabel="执行人"
            okText="添加执行人"
            roles={assigneeRoles}
            search={(role, query, signal) =>
              searchActionAssigneeCandidates(action.id, role.value as 'primary' | 'collaborator', role.actorKind, query, signal)
            }
            add={(role, candidate) =>
              run(
                '添加执行人',
                () => addActionAssignee(action.id, candidate.actor_kind, candidate.actor_id, role.value as 'primary' | 'collaborator'),
                { notify: false },
              )
            }
            onAccessLost={refresh}
          />
          <CommandTextDialog
            container="modal"
            open={cancelOpen}
            onClose={() => setCancelOpen(false)}
            title="取消整改项"
            description="取消后整改项不能恢复，请说明取消原因。"
            fieldName="reason"
            fieldLabel="取消原因"
            okText="确认取消"
            danger
            run={(reason) =>
              run('取消整改项', () => transitionActionItem(action.id, 'cancel', reason), {
                fields: ['reason'],
                notify: false,
              })
            }
          />
        </>
      )}
    </Flex>
  )
}
