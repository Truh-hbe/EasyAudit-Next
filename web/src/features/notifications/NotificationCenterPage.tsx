import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

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

type InboxMode = 'all' | 'unread'

type InboxState =
  | { status: 'loading'; key: string }
  | { status: 'error'; key: string; message: string }
  | { status: 'ready'; key: string; data: NotificationInboxResponse }

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
  const [mode, setMode] = useState<InboxMode>('all')
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<InboxState>({ status: 'loading', key: 'all:0' })
  const [markingId, setMarkingId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const requestSequenceRef = useRef(0)
  const currentViewRef = useRef({ mode, offset })
  currentViewRef.current = { mode, offset }

  const viewKey = `${mode}:${offset}`

  useEffect(() => {
    const controller = new AbortController()
    const sequence = requestSequenceRef.current + 1
    requestSequenceRef.current = sequence
    const requestedKey = viewKey
    setState({ status: 'loading', key: requestedKey })
    setMessage(null)

    void listNotifications(mode === 'unread', PAGE_SIZE, offset, controller.signal)
      .then((data) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({ status: 'ready', key: requestedKey, data })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestSequenceRef.current !== sequence) return
        setState({
          status: 'error',
          key: requestedKey,
          message: errorMessage(error, '通知请求失败'),
        })
      })

    return () => controller.abort()
  }, [mode, offset, revision, viewKey])

  function changeMode(nextMode: InboxMode) {
    if (nextMode === mode) return
    setMode(nextMode)
    setOffset(0)
    setMarkingId(null)
    setMessage(null)
  }

  async function markRead(notificationId: string) {
    const commandView = currentViewRef.current
    setMarkingId(notificationId)
    setMessage(null)
    try {
      await markNotificationRead(notificationId)
      const currentView = currentViewRef.current
      if (currentView.mode !== commandView.mode || currentView.offset !== commandView.offset) return
      setMessage('已由服务器确认阅读状态。')
      setRevision((value) => value + 1)
    } catch (error) {
      const currentView = currentViewRef.current
      if (currentView.mode !== commandView.mode || currentView.offset !== commandView.offset) return
      setMessage(errorMessage(error, '标记已读失败'))
      if (error instanceof ApiError && error.status === 404) {
        setRevision((value) => value + 1)
      }
    } finally {
      const currentView = currentViewRef.current
      if (currentView.mode === commandView.mode && currentView.offset === commandView.offset) {
        setMarkingId(null)
      }
    }
  }

  const currentState = state.key === viewKey ? state : { status: 'loading', key: viewKey } as const
  const data = currentState.status === 'ready' ? currentState.data : null
  const hasPrevious = offset > 0
  const hasPossibleNext = data !== null && data.items.length === data.limit

  return (
    <section className="surface-page" aria-labelledby="notifications-title">
      <div className="page-heading">
        <div>
          <h1 id="notifications-title">通知</h1>
        </div>
        <p>未读总数 {data?.unread_count ?? '—'}</p>
      </div>

      <section className="surface-card" aria-label="通知视图">
        <div className="command-stack">
          <button
            type="button"
            className={mode === 'all' ? undefined : 'secondary'}
            aria-pressed={mode === 'all'}
            onClick={() => changeMode('all')}
          >
            全部
          </button>
          <button
            type="button"
            className={mode === 'unread' ? undefined : 'secondary'}
            aria-pressed={mode === 'unread'}
            onClick={() => changeMode('unread')}
          >
            未读{data === null ? '' : ` (${data.unread_count})`}
          </button>
        </div>
        <p className="empty-note">
          Notification 是历史投递记录，不代表当前责任或访问权限；打开目标后仍由目标 API 重新授权。
        </p>
      </section>

      {currentState.status === 'loading' ? (
        <section className="surface-card"><p>正在读取服务器通知…</p></section>
      ) : null}

      {currentState.status === 'error' ? (
        <section className="surface-card" role="alert">
          <p>{currentState.message}</p>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button>
        </section>
      ) : null}

      {data !== null && data.items.length === 0 ? (
        <section className="surface-card"><p className="empty-note">当前视图暂无通知。</p></section>
      ) : null}

      {data !== null && data.items.length > 0 ? (
        <ol className="surface-list" aria-label={mode === 'unread' ? '未读通知' : '全部通知'}>
          {data.items.map((item) => {
            const targetPath = subjectPath(item.subject)
            return (
              <li key={item.id}>
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.body}</p>
                </div>
                <span>{notificationKindText(item.kind)} · {formatDateTime(item.created_at)}</span>
                <span>{item.read_at === null ? '未读' : `已读 ${formatDateTime(item.read_at)}`}</span>
                <span>{subjectText(item.subject)}</span>
                <div className="command-stack">
                  {targetPath === null ? (
                    <span>目标类型不可用</span>
                  ) : (
                    <Link to={targetPath}>打开当前目标</Link>
                  )}
                  {item.read_at === null ? (
                    <button
                      type="button"
                      className="secondary"
                      disabled={markingId !== null}
                      onClick={() => void markRead(item.id)}
                    >
                      {markingId === item.id ? '正在确认…' : '标记已读'}
                    </button>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ol>
      ) : null}

      {data !== null ? (
        <section className="surface-card" aria-label="通知分页">
          <p>当前 offset {data.offset} · 每页上限 {data.limit}</p>
          <div className="command-stack">
            <button
              type="button"
              className="secondary"
              disabled={!hasPrevious}
              onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
            >上一页</button>
            <button
              type="button"
              className="secondary"
              disabled={!hasPossibleNext}
              onClick={() => setOffset((value) => value + PAGE_SIZE)}
            >下一页</button>
          </div>
          {mode === 'all' ? (
            <p className="empty-note">通知列表不显示总条数；“下一页”仅表示当前页已满。</p>
          ) : null}
        </section>
      ) : null}

      {message === null ? null : <p role="status">{message}</p>}
    </section>
  )
}
