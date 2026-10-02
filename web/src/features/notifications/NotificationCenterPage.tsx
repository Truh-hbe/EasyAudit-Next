import { Alert, App, Badge, Button, Card, Flex, Radio, Spin, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../../api/client'
import {
  listNotifications,
  markNotificationRead,
} from '../../api/notifications'
import type {
  NotificationInboxResponse,
  NotificationResponse,
  NotificationSubjectResponse,
} from '../../api/notifications'
import { formatDateTime } from '../../product/format'
import { ButtonLink } from '../../ui/ButtonLink'
import { InitialLoading } from '../../ui/InitialLoading'
import { ItemList } from '../../ui/ItemList'
import { PageHeader } from '../../ui/PageHeader'

type InboxMode = 'all' | 'unread'

interface InboxState {
  // 仅保留最近一次成功的结果；请求失败时清空，不用旧数据兜底。
  data: NotificationInboxResponse | null
  dataKey: string | null
  loading: boolean
  error: string | null
}

interface Notice {
  type: 'warning' | 'error'
  text: string
}

const PAGE_SIZE = 20

function notificationKindText(kind: NotificationResponse['kind']): string {
  const labels: Record<NotificationResponse['kind'], string> = {
    case_membership_added: '审查成员变更',
    finding_participant_added: '发现项参与关系',
    action_assignee_added: '整改项执行关系',
    finding_submitted_for_verification: '发现项待验证',
    manual_finding_nudge: '发现项催办',
    manual_action_nudge: '整改项催办',
    automatic_case_reminder: '审查到期提醒',
    automatic_action_reminder: '整改项到期提醒',
  }
  return labels[kind]
}

function subjectPath(subject: NotificationSubjectResponse): string | null {
  switch (subject.kind) {
    case 'review_case':
      return `/review-cases/${subject.id}`
    case 'finding':
      return `/findings/${subject.id}`
    case 'action_item':
      return `/action-items/${subject.id}`
    default:
      return null
  }
}

function subjectText(subject: NotificationSubjectResponse): string {
  switch (subject.kind) {
    case 'review_case':
      return '审查活动'
    case 'finding':
      return '发现项'
    case 'action_item':
      return '整改项'
    default:
      return '未知目标'
  }
}

const ACCESS_LOST_TEXT = '内容不存在或无权访问'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function NotificationCenterPage() {
  const { message } = App.useApp()
  const [mode, setMode] = useState<InboxMode>('all')
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<InboxState>({ data: null, dataKey: null, loading: true, error: null })
  const [markingId, setMarkingId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const requestSequenceRef = useRef(0)
  const commandSequenceRef = useRef(0)
  const markingRef = useRef<{ command: number; id: string } | null>(null)
  const currentViewRef = useRef({ mode, offset })
  currentViewRef.current = { mode, offset }

  const viewKey = `${mode}:${offset}`

  useEffect(() => {
    const controller = new AbortController()
    const sequence = requestSequenceRef.current + 1
    requestSequenceRef.current = sequence
    const requestedKey = viewKey
    setState((previous) => ({ ...previous, loading: true, error: null }))

    void listNotifications(mode === 'unread', PAGE_SIZE, offset, controller.signal)
      .then((data) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({ data, dataKey: requestedKey, loading: false, error: null })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({
          data: null,
          dataKey: null,
          loading: false,
          error: errorMessage(error, '通知请求失败'),
        })
      })

    return () => controller.abort()
  }, [mode, offset, revision, viewKey])

  function reload() {
    setNotice(null)
    setRevision((value) => value + 1)
  }

  function changeMode(nextMode: InboxMode) {
    if (nextMode === mode) return
    setMode(nextMode)
    setOffset(0)
    setNotice(null)
  }

  function changeOffset(next: (value: number) => number) {
    setOffset(next)
    setNotice(null)
  }

  // 写请求的锁和视图无关：切换视图不释放锁；每个请求只结束自己的状态。
  async function markRead(notificationId: string) {
    if (markingRef.current !== null) return
    const command = commandSequenceRef.current + 1
    commandSequenceRef.current = command
    markingRef.current = { command, id: notificationId }
    const commandView = currentViewRef.current
    setMarkingId(notificationId)
    setNotice(null)
    // 写成功或结果未知后都要让“当前”视图重新读取；晚到的旧响应由读请求序号丢弃。
    const refetch = () => setRevision((value) => value + 1)
    try {
      await markNotificationRead(notificationId)
      const currentView = currentViewRef.current
      if (currentView.mode === commandView.mode && currentView.offset === commandView.offset) {
        void message.success('已标记为已读')
      }
      refetch()
    } catch (error) {
      // 写操作不自动重放：只重新读取列表核对，是否再次标记由用户决定。
      if (error instanceof ApiError && error.status === 401) {
        // Session 失效由 client 的统一处理接管。
      } else if (error instanceof ApiError && error.status === 403) {
        // 授权失效：立即移除受保护内容，并让还在途的读响应失效。
        requestSequenceRef.current += 1
        setState({ data: null, dataKey: null, loading: false, error: ACCESS_LOST_TEXT })
      } else if (error instanceof ApiError && error.status === 404) {
        setState((previous) =>
          previous.data === null
            ? previous
            : {
                ...previous,
                data: { ...previous.data, items: previous.data.items.filter((item) => item.id !== notificationId) },
              },
        )
        setNotice({ type: 'warning', text: `${ACCESS_LOST_TEXT}，正在获取最新状态。` })
        refetch()
      } else if (error instanceof ApiError && error.status === 409) {
        setNotice({ type: 'warning', text: '数据已变化，正在获取最新状态。' })
        refetch()
      } else if (error instanceof ApiError && error.status < 500) {
        setNotice({ type: 'error', text: errorMessage(error, '标记已读失败') })
      } else {
        setNotice({
          type: 'warning',
          text: '未确认是否已标记为已读，已重新读取列表供核对；如仍为未读可再次点击。',
        })
        refetch()
      }
    } finally {
      if (markingRef.current?.command === command) {
        markingRef.current = null
        setMarkingId(null)
      }
    }
  }

  const data = state.dataKey === viewKey ? state.data : null
  const initialLoading = state.loading && data === null
  const refreshing = state.loading && data !== null
  const hasPrevious = offset > 0
  const hasPossibleNext = data !== null && data.items.length === data.limit

  function renderItem(item: NotificationResponse) {
    const targetPath = subjectPath(item.subject)
    return (
      <Flex vertical gap={8}>
        <Flex vertical gap={4}>
          <Typography.Text strong>{item.title}</Typography.Text>
          <Typography.Text>{item.body}</Typography.Text>
        </Flex>
        <Flex align="center" wrap gap={8}>
          {item.read_at === null ? (
            <Badge color="blue" text="未读" />
          ) : (
            <Typography.Text type="secondary">已读 {formatDateTime(item.read_at)}</Typography.Text>
          )}
          <Typography.Text type="secondary">
            {notificationKindText(item.kind)} · {formatDateTime(item.created_at)}
          </Typography.Text>
          <Typography.Text type="secondary">{subjectText(item.subject)}</Typography.Text>
        </Flex>
        <Flex align="center" wrap gap={8}>
          {targetPath === null ? (
            <Typography.Text type="secondary">目标类型不可用</Typography.Text>
          ) : (
            <ButtonLink to={targetPath}>打开当前目标</ButtonLink>
          )}
          {item.read_at === null ? (
            <Button
              loading={markingId === item.id}
              disabled={markingId !== null}
              onClick={() => void markRead(item.id)}
            >
              标记已读
            </Button>
          ) : null}
        </Flex>
      </Flex>
    )
  }

  const emptyText =
    offset > 0
      ? '当前页没有通知。'
      : mode === 'unread'
        ? '没有未读通知。'
        : '暂无通知。'

  return (
    <Flex vertical gap={16} aria-busy={initialLoading}>
      <PageHeader
        title="通知"
        titleId="notifications-title"
        meta={<Typography.Text type="secondary">未读总数 {data?.unread_count ?? '—'}</Typography.Text>}
      />

      <Card>
        <Flex vertical gap={12}>
          <Radio.Group
            optionType="button"
            aria-label="通知视图"
            value={mode}
            onChange={(event) => changeMode(event.target.value as InboxMode)}
            options={[
              { value: 'all', label: '全部' },
              { value: 'unread', label: `未读${data === null ? '' : ` (${data.unread_count})`}` },
            ]}
          />
          <Typography.Text type="secondary">
            通知是历史投递记录，不代表当前责任或访问权限；打开目标后仍会重新校验权限。
          </Typography.Text>
        </Flex>
      </Card>

      {state.error === null ? null : (
        <Alert
          type="error"
          showIcon
          title={state.error}
          action={<Button size="small" onClick={reload}>重新加载</Button>}
        />
      )}
      {notice === null ? null : (
        <Alert type={notice.type} showIcon role="status" title={notice.text} closable={{ onClose: () => setNotice(null) }} />
      )}

      {initialLoading ? <Card><InitialLoading label="正在加载通知" rows={6} /></Card> : null}

      {data === null ? null : (
        <Spin spinning={refreshing}>
          <Card>
            <Flex vertical gap={16}>
              <ItemList
                label={mode === 'unread' ? '未读通知' : '全部通知'}
                emptyText={emptyText}
                emptyAction={mode === 'unread' ? <Button onClick={() => changeMode('all')}>查看全部通知</Button> : null}
                items={data.items.map((item) => ({ key: item.id, content: renderItem(item) }))}
              />
              <Flex component="nav" aria-label="通知分页" align="center" wrap gap={8}>
                <Button
                  disabled={!hasPrevious}
                  onClick={() => changeOffset((value) => Math.max(0, value - PAGE_SIZE))}
                >上一页</Button>
                <Typography.Text type="secondary">第 {Math.floor(data.offset / data.limit) + 1} 页</Typography.Text>
                <Button
                  disabled={!hasPossibleNext}
                  onClick={() => changeOffset((value) => value + PAGE_SIZE)}
                >下一页</Button>
              </Flex>
              {mode === 'all' ? (
                <Typography.Text type="secondary">
                  通知列表不显示总条数；“下一页”仅表示当前页已满。
                </Typography.Text>
              ) : null}
            </Flex>
          </Card>
        </Spin>
      )}
    </Flex>
  )
}
