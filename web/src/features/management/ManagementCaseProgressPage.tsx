import { NotificationOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Empty, Flex, Result, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

import { nudgeActionItem, nudgeFinding } from '../../api/collaboration'
import type { NudgeResponse } from '../../api/collaboration'
import { getManagedReviewCaseProgress } from '../../api/management'
import type {
  ActionLifecycleCounts,
  ManagementActionDeadlineItem,
  ManagementFindingProgress,
} from '../../api/product'
import { NOT_AVAILABLE_TEXT } from '../../product/commandFailure'
import { formatDateTime } from '../../product/format'
import { ButtonLink } from '../../ui/ButtonLink'
import { InitialLoading } from '../../ui/InitialLoading'
import { PageHeader } from '../../ui/PageHeader'
import { isDeadlineStatus, StatusTag } from '../../ui/StatusTag'
import { isUnavailable, useScopedResource } from '../useScopedResource'

interface NudgeNotice {
  type: 'success' | 'error'
  message: string
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function findingActionText(actions: ActionLifecycleCounts): string {
  return `共 ${actions.total} / 待开始 ${actions.todo} / 执行中 ${actions.in_progress} / 已完成 ${actions.done} / 已逾期 ${actions.overdue} / 即将到期 ${actions.due_soon}`
}

const emptyImage = Empty.PRESENTED_IMAGE_SIMPLE

export function ManagementCaseProgressPage() {
  const { caseId } = useParams()
  const currentCaseIdRef = useRef(caseId)
  currentCaseIdRef.current = caseId
  const [revision, setRevision] = useState(0)
  const [nudgeBusyKey, setNudgeBusyKey] = useState<string | null>(null)
  const [nudgeNotice, setNudgeNotice] = useState<NudgeNotice | null>(null)

  useEffect(() => {
    setNudgeBusyKey(null)
    setNudgeNotice(null)
  }, [caseId])

  const progress = useScopedResource(
    caseId ?? null,
    revision,
    (signal) => getManagedReviewCaseProgress(caseId ?? '', signal),
    '管理进度请求失败',
  )

  async function runNudge(key: string, command: () => Promise<NudgeResponse>) {
    const commandCaseId = caseId
    setNudgeBusyKey(key)
    setNudgeNotice(null)
    try {
      const result = await command()
      if (currentCaseIdRef.current !== commandCaseId) return
      setNudgeNotice({
        type: 'success',
        message: `服务器已确认催办：已通知 ${result.recipient_count} 人，操作记录 ${result.activity_id}。`,
      })
      setRevision((value) => value + 1)
    } catch (error) {
      if (currentCaseIdRef.current !== commandCaseId) return
      setNudgeNotice({ type: 'error', message: errorMessage(error, '催办失败') })
      // 403/404：重读管理进度，授权丢失时受保护内容立即移除。
      if (isUnavailable(error)) {
        setRevision((value) => value + 1)
      }
    } finally {
      if (currentCaseIdRef.current === commandCaseId) {
        setNudgeBusyKey(null)
      }
    }
  }

  if (caseId === undefined || progress.status === 'unavailable') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="管理进度" />
        <Card>
          <Result
            status="404"
            title={NOT_AVAILABLE_TEXT}
            extra={<ButtonLink to="/management">返回管理视图</ButtonLink>}
          />
        </Card>
      </Flex>
    )
  }

  if (progress.status === 'loading') {
    return (
      <Flex vertical gap={16} aria-busy="true">
        <PageHeader title="管理进度" />
        <Card><InitialLoading label="正在读取管理进度" rows={6} /></Card>
      </Flex>
    )
  }

  if (progress.status === 'error') {
    return (
      <Flex vertical gap={16}>
        <PageHeader title="管理进度" />
        <Alert
          type="error"
          showIcon
          title={progress.message}
          action={<Button size="small" onClick={() => setRevision((value) => value + 1)}>重新加载</Button>}
        />
      </Flex>
    )
  }

  const data = progress.data
  const nudgeDisabled = nudgeBusyKey !== null

  function nudgeButton(key: string, label: string, command: () => Promise<NudgeResponse>) {
    return (
      <Button
        icon={<NotificationOutlined aria-hidden />}
        disabled={nudgeDisabled}
        loading={nudgeBusyKey === key}
        onClick={() => void runNudge(key, command)}
      >{label}</Button>
    )
  }

  const findingColumns: TableColumnsType<ManagementFindingProgress> = [
    {
      title: '发现项',
      key: 'title',
      render: (_value: unknown, finding) => <Link to={`/findings/${finding.id}`}>{finding.title}</Link>,
    },
    {
      title: '状态',
      key: 'status',
      render: (_value: unknown, finding) => (
        <Flex wrap gap={4}>
          <StatusTag kind="severity" value={finding.severity} />
          <StatusTag kind="finding" value={finding.lifecycle} />
        </Flex>
      ),
    },
    {
      title: '提出时间',
      key: 'raised_at',
      render: (_value: unknown, finding) => formatDateTime(finding.raised_at),
    },
    {
      title: '整改项',
      key: 'actions',
      width: 200,
      render: (_value: unknown, finding) => findingActionText(finding.actions),
    },
    {
      title: '操作',
      key: 'operations',
      render: (_value: unknown, finding) =>
        nudgeButton(`finding:${finding.id}`, '催办发现项', () => nudgeFinding(finding.id)),
    },
  ]

  const actionColumns: TableColumnsType<ManagementActionDeadlineItem> = [
    {
      title: '整改项',
      key: 'title',
      render: (_value: unknown, action) => <Link to={`/action-items/${action.id}`}>{action.title}</Link>,
    },
    {
      title: '状态',
      key: 'lifecycle',
      render: (_value: unknown, action) => <StatusTag kind="actionItem" value={action.lifecycle} />,
    },
    {
      title: '到期时间',
      key: 'due_at',
      render: (_value: unknown, action) => formatDateTime(action.due_at),
    },
    {
      title: '操作',
      key: 'operations',
      render: (_value: unknown, action) =>
        nudgeButton(`action:${action.id}`, '催办整改项', () => nudgeActionItem(action.id)),
    },
  ]

  function section<T extends { id: string }>(
    title: string,
    emptyText: string,
    items: T[],
    columns: TableColumnsType<T>,
  ) {
    return (
      <Card title={<h2>{title}</h2>}>
        <Table<T>
          size="middle"
          rowKey="id"
          columns={columns}
          dataSource={items}
          pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <Empty image={emptyImage} description={emptyText} /> }}
        />
      </Card>
    )
  }

  return (
    <Flex vertical gap={16} aria-busy={progress.refreshing}>
      <PageHeader
        title={data.case.title}
        titleId="management-progress-title"
        meta={
          <>
            <StatusTag kind="reviewCase" value={data.case.lifecycle} />
            <Typography.Text type="secondary">{`数据时间 ${formatDateTime(data.as_of)}`}</Typography.Text>
          </>
        }
        extra={
          <>
            <ButtonLink to="/management">返回管理视图</ButtonLink>
            <ButtonLink to={`/review-cases/${data.case.id}`}>打开审查活动</ButtonLink>
          </>
        }
      />

      {progress.refreshError === null ? null : (
        <Alert
          type="warning"
          showIcon
          title={`${progress.refreshError}；当前显示的是上一次读取的内容。`}
          action={<Button size="small" onClick={() => setRevision((value) => value + 1)}>重新加载</Button>}
        />
      )}

      {nudgeNotice === null ? null : <Alert type={nudgeNotice.type} showIcon title={nudgeNotice.message} />}

      <Card title={<h2>进度概况</h2>}>
        <Flex vertical gap={8}>
        <Descriptions column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="截止状态">
            {isDeadlineStatus(data.case.deadline_bucket)
              ? <StatusTag kind="deadline" value={data.case.deadline_bucket} />
              : '未临近截止'}
          </Descriptions.Item>
          <Descriptions.Item label="计划结束">{formatDateTime(data.case.planned_end_at)}</Descriptions.Item>
          <Descriptions.Item label="发现项总数">{data.case.findings.total}</Descriptions.Item>
          <Descriptions.Item label="发现项已关闭">{data.case.findings.closed}</Descriptions.Item>
          <Descriptions.Item label="整改项总数">{data.case.actions.total}</Descriptions.Item>
          <Descriptions.Item label="整改项已完成">{data.case.actions.done}</Descriptions.Item>
          <Descriptions.Item label="整改项已逾期">{data.case.actions.overdue}</Descriptions.Item>
          <Descriptions.Item label="整改项即将到期">{data.case.actions.due_soon}</Descriptions.Item>
        </Descriptions>
        <Typography.Text type="secondary">本页只展示服务器给出的计数，不计算百分比、风险分或截止状态。</Typography.Text>
        </Flex>
      </Card>

      {section('可见的发现项', '当前没有可见的发现项。', data.findings, findingColumns)}
      {section('已逾期整改项', '当前没有已逾期整改项。', data.overdue_actions, actionColumns)}
      {section('即将到期整改项', '当前没有即将到期整改项。', data.due_soon_actions, actionColumns)}

      <Typography.Text type="secondary">此处只提供催办入口；被催办的人由服务器按审查场景确定。</Typography.Text>
    </Flex>
  )
}
