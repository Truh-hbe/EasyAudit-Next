import { Alert, App, Badge, Button, Card, Empty, Flex, Skeleton, Spin, Table, Typography } from 'antd'
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
    setMarkingId(null)
    setNotice(null)
  }

  function changeOffset(next: (value: number) => number) {
    setOffset(next)
    setMarkingId(null)
    setNotice(null)
  }

  async function markRead(notificationId: string) {
    const commandView = currentViewRef.current
    const inCommandView = () => {
      const currentView = currentViewRef.current
      return currentView.mode === commandView.mode && currentView.offset === commandView.offset
    }
    setMarkingId(notificationId)
    setNotice(null)
    try {
      await markNotificationRead(notificationId)
      if (!inCommandView()) return
      void message.success('已标记为已读')
      setRevision((value) => value + 1)
    } catch (error) {
      if (!inCommandView()) return
      // 写操作不自动重放：只重新读取列表核对，是否再次标记由用户决定。
      if (error instanceof ApiError && error.status === 409) {
        setNotice({ type: 'warning', text: '数据已变化，正在获取最新状态。' })
        setRevision((value) => value + 1)
      } else if (error instanceof ApiError && error.status === 404) {
        setNotice({ type: 'warning', text: errorMessage(error, '通知已不存在，正在获取最新状态。') })
        setRevision((value) => value + 1)
      } else if (error instanceof ApiError && error.status < 500) {
        setNotice({ type: 'error', text: errorMessage(error, '标记已读失败') })
      } else {
        setNotice({
          type: 'warning',
          text: '未确认是否已标记为已读，已重新读取列表供核对；如仍为未读可再次点击。',
        })
        setRevision((value) => value + 1)
      }
    } finally {
      if (inCommandView()) setMarkingId(null)
    }
  }

  const data = state.dataKey === viewKey ? state.data : null
  const refreshing = state.loading && data !== null
  const hasPrevious = offset > 0
  const hasPossibleNext = data !== null && data.items.length === data.limit

  const columns = [
    {
      key: 'notification',
      render: (_: unknown, item: NotificationResponse) => {
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
                  disabled={markingId !== null && markingId !== item.id}
                  onClick={() => void markRead(item.id)}
                >
                  标记已读
                </Button>
              ) : null}
            </Flex>
          </Flex>
        )
      },
    },
  ]

  const emptyText =
    offset > 0
      ? '当前页没有通知。'
      : mode === 'unread'
        ? '没有未读通知。'
        : '暂无通知。'

  return (
    <Flex vertical gap={16}>
      <PageHeader
        title="通知"
        titleId="notifications-title"
        meta={<Typography.Text type="secondary">未读总数 {data?.unread_count ?? '—'}</Typography.Text>}
      />

      <Card>
        <Flex vertical gap={12}>
          <Flex role="group" aria-label="通知视图" align="center" wrap gap={8}>
            <Button
              type={mode === 'all' ? 'primary' : 'default'}
              aria-pressed={mode === 'all'}
              onClick={() => changeMode('all')}
            >
              全部
            </Button>
            <Button
              type={mode === 'unread' ? 'primary' : 'default'}
              aria-pressed={mode === 'unread'}
              onClick={() => changeMode('unread')}
            >
              未读{data === null ? '' : ` (${data.unread_count})`}
            </Button>
          </Flex>
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

      {state.loading && data === null ? (
        <Card><Skeleton active paragraph={{ rows: 6 }} /></Card>
      ) : null}

      {data === null ? null : (
        <Spin spinning={refreshing}>
          <Card>
            <Flex vertical gap={16}>
              <Table<NotificationResponse>
                size="middle"
                showHeader={false}
                pagination={false}
                rowKey="id"
                aria-label={mode === 'unread' ? '未读通知' : '全部通知'}
                columns={columns}
                dataSource={data.items}
                locale={{
                  emptyText: (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText}>
                      {mode === 'unread' ? <Button onClick={() => changeMode('all')}>查看全部通知</Button> : null}
                    </Empty>
                  ),
                }}
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
