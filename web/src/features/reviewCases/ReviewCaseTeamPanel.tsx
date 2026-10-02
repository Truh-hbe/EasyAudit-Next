import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Drawer, Flex, Form, Grid, Select, Spin, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../../api/client'
import {
  addReviewCaseMember,
  removeReviewCaseMember,
  searchReviewCaseMemberCandidates,
} from '../../api/product'
import type {
  CaseMemberCandidateResponse,
  CaseMemberViewResponse,
  ReviewCaseResponse,
} from '../../api/product'
import { formatDateTime } from '../../product/format'
import type { ScenarioCaseRoleOption } from '../../scenarios/registry'
import { InitialLoading } from '../../ui/InitialLoading'
import { ItemList } from '../../ui/ItemList'

interface ReviewCaseTeamPanelProps {
  reviewCase: ReviewCaseResponse
  roleOptions: readonly ScenarioCaseRoleOption[]
  members: CaseMemberViewResponse[]
  membersLoading: boolean
  membersUnavailable: boolean
  membersError: string | null
  onTeamChanged: () => void
  // 写请求返回 404：审查活动已不可见，由页面重新确认主授权并移除受保护内容。
  onAccessLost: () => void
}

export function roleLabelForCaseMember(
  roleKey: string,
  roleOptions: readonly ScenarioCaseRoleOption[],
): string {
  return roleOptions.find((option) => option.roleKey === roleKey)?.label ?? roleKey
}

const LAST_MANAGER_DETAIL = 'Cannot remove the final effective Case manager'
const SEARCH_DEBOUNCE_MS = 300

export type TeamAction = 'search' | 'add' | 'remove'

// 对应 design.md「交互状态」：409 按原因区分，写入结果未知不属于 409。
export type TeamFailure =
  | { kind: 'session' }
  | { kind: 'forbidden'; message: string }
  | { kind: 'gone'; message: string }
  | { kind: 'last-manager'; message: string }
  | { kind: 'changed'; message: string }
  | { kind: 'retry-later'; message: string }
  | { kind: 'rejected'; message: string }
  | { kind: 'unknown-result'; message: string }

export function classifyTeamFailure(error: unknown, action: TeamAction): TeamFailure {
  if (error instanceof ApiError) {
    if (error.status === 401) return { kind: 'session' }
    if (error.status === 403) {
      return { kind: 'forbidden', message: '当前用户没有管理审查团队的权限。' }
    }
    if (error.status === 404) return { kind: 'gone', message: '内容不存在或无权访问' }
    if (error.status === 409) {
      if (action === 'remove' && error.detail === LAST_MANAGER_DETAIL) {
        return {
          kind: 'last-manager',
          message: '审查活动至少需要保留一名有效的审查组长，无法移除最后一名管理者。',
        }
      }
      return {
        kind: 'changed',
        message:
          action === 'add'
            ? '该成员已在团队中，或团队已发生变化，正在获取最新状态。'
            : '数据已变化，正在获取最新状态。',
      }
    }
    if (error.status === 429 || error.status === 503) {
      const wait = error.retryAfter === null ? '稍后' : `${error.retryAfter} 秒后`
      return { kind: 'retry-later', message: `服务繁忙，请${wait}手动重试。` }
    }
    if (error.status < 500) return { kind: 'rejected', message: error.detail }
  }
  if (action === 'search') {
    return {
      kind: 'unknown-result',
      message: error instanceof Error ? error.message : '候选成员请求失败',
    }
  }
  return {
    kind: 'unknown-result',
    message: `未确认是否${action === 'add' ? '已添加' : '已移除'}成员，已重新读取团队成员供核对；如未生效可再次操作。`,
  }
}

interface AddMemberDrawerProps {
  open: boolean
  reviewCase: ReviewCaseResponse
  roleOptions: readonly ScenarioCaseRoleOption[]
  onClose: () => void
  onAdded: () => void
  onTeamChanged: () => void
  onAccessLost: () => void
}

interface AddMemberFormValues {
  roleKey: string
  member?: { value: string; label: string }
}

function AddMemberDrawer({
  open,
  reviewCase,
  roleOptions,
  onClose,
  onAdded,
  onTeamChanged,
  onAccessLost,
}: AddMemberDrawerProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<AddMemberFormValues>()
  const [candidates, setCandidates] = useState<CaseMemberCandidateResponse[]>([])
  const [searching, setSearching] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<TeamFailure | null>(null)
  const searchRef = useRef<{ controller: AbortController; timer: number | null } | null>(null)

  function cancelSearch() {
    const current = searchRef.current
    if (current === null) return
    current.controller.abort()
    if (current.timer !== null) window.clearTimeout(current.timer)
    searchRef.current = null
  }

  // 候选人只来自服务端授权的候选接口；任何失败都清空，不保留过期名称。
  function runSearch(roleKey: string, query: string, delay: number) {
    cancelSearch()
    if (!roleKey) {
      setCandidates([])
      setSearching(false)
      return
    }
    const controller = new AbortController()
    setSearching(true)
    setError(null)
    const timer = window.setTimeout(() => {
      void searchReviewCaseMemberCandidates(reviewCase.id, roleKey, query, controller.signal)
        .then((data) => {
          if (controller.signal.aborted) return
          setCandidates(data)
          setSearching(false)
        })
        .catch((failure: unknown) => {
          if (controller.signal.aborted) return
          setCandidates([])
          setSearching(false)
          const classified = classifyTeamFailure(failure, 'search')
          setError(classified)
          if (classified.kind === 'gone') onAccessLost()
        })
    }, delay)
    searchRef.current = { controller, timer }
  }

  useEffect(() => {
    if (!open) return undefined
    setCandidates([])
    setError(null)
    runSearch(roleOptions[0]?.roleKey ?? '', '', 0)
    return () => {
      cancelSearch()
      setCandidates([])
      setSearching(false)
      setSubmitting(false)
    }
    // runSearch 只依赖 reviewCase.id 与稳定的 setter；仅在打开/切换活动时重新取候选。
  }, [open, reviewCase.id, roleOptions])

  async function submit(values: AddMemberFormValues) {
    if (values.member === undefined || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await addReviewCaseMember(reviewCase.id, values.member.value, values.roleKey)
      onAdded()
    } catch (failure: unknown) {
      const classified = classifyTeamFailure(failure, 'add')
      setCandidates([])
      form.setFieldValue('member', undefined)
      if (classified.kind === 'gone') {
        onAccessLost()
        return
      }
      setError(classified)
      // 冲突或结果未知：写请求不自动重放，只重新读取团队供用户核对。
      if (classified.kind === 'changed' || classified.kind === 'unknown-result') onTeamChanged()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="添加成员"
      open={open}
      onClose={onClose}
      size={screens.sm ? 480 : '100%'}
      destroyOnHidden
    >
      <Form<AddMemberFormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{ roleKey: roleOptions[0]?.roleKey }}
        disabled={submitting}
        onFinish={(values) => void submit(values)}
      >
        {error === null || error.kind === 'session' ? null : (
          <Alert
            type={error.kind === 'changed' || error.kind === 'unknown-result' ? 'warning' : 'error'}
            showIcon
            title={error.message}
            style={{ marginBottom: 16 }}
          />
        )}
        <Form.Item label="团队角色" name="roleKey" rules={[{ required: true, message: '请选择团队角色' }]}>
          <Select
            options={roleOptions.map((option) => ({ value: option.roleKey, label: option.label }))}
            onChange={(roleKey: string) => {
              form.setFieldValue('member', undefined)
              setCandidates([])
              runSearch(roleKey, '', 0)
            }}
          />
        </Form.Item>
        <Form.Item label="成员" name="member" rules={[{ required: true, message: '请选择要添加的成员' }]}>
          <Select
            labelInValue
            showSearch={{
              filterOption: false,
              onSearch: (query: string) => runSearch(form.getFieldValue('roleKey') as string, query, SEARCH_DEBOUNCE_MS),
            }}
            placeholder="输入姓名搜索"
            loading={searching}
            notFoundContent={searching ? <Spin size="small" /> : '没有找到候选成员'}
            options={candidates.map((candidate) => ({ value: candidate.user_id, label: candidate.display_name }))}
          />
        </Form.Item>
        <Flex justify="flex-end" gap={8}>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            添加成员
          </Button>
        </Flex>
      </Form>
    </Drawer>
  )
}

export function ReviewCaseTeamPanel({
  reviewCase,
  roleOptions,
  members,
  membersLoading,
  membersUnavailable,
  membersError,
  onTeamChanged,
  onAccessLost,
}: ReviewCaseTeamPanelProps) {
  const { message, modal } = App.useApp()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [removingKey, setRemovingKey] = useState<string | null>(null)
  const removingRef = useRef(false)
  const [notice, setNotice] = useState<TeamFailure | null>(null)

  // 切换审查活动时丢弃上一个活动的弹层与提示。
  useEffect(() => {
    setDrawerOpen(false)
    setNotice(null)
  }, [reviewCase.id])

  async function removeMember(member: CaseMemberViewResponse) {
    if (removingRef.current) return
    removingRef.current = true
    setRemovingKey(`${member.user_id}:${member.role_key}`)
    setNotice(null)
    try {
      await removeReviewCaseMember(reviewCase.id, member.user_id, member.role_key)
      void message.success('已移除成员')
      onTeamChanged()
    } catch (error: unknown) {
      const failure = classifyTeamFailure(error, 'remove')
      if (failure.kind === 'gone') {
        onAccessLost()
      } else {
        // 失败时不改动已渲染的成员；冲突或结果未知时重新读取，由用户核对后再决定。
        setNotice(failure)
        if (failure.kind === 'changed' || failure.kind === 'unknown-result') onTeamChanged()
      }
    } finally {
      removingRef.current = false
      setRemovingKey(null)
    }
  }

  function confirmRemove(member: CaseMemberViewResponse) {
    modal.confirm({
      title: '移除成员',
      content: `将 ${member.display_name}（${roleLabelForCaseMember(member.role_key, roleOptions)}）从审查团队中移除。`,
      okText: '确认移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      // 失败由面板内的提示呈现，这里总是正常结束以关闭确认框。
      onOk: () => removeMember(member),
    })
  }

  const canManage = roleOptions.length > 0

  return (
    <section aria-labelledby="case-team-title">
      <Card
        title={<h2 id="case-team-title">团队管理</h2>}
        extra={
          canManage ? (
            <Button icon={<PlusOutlined aria-hidden />} onClick={() => setDrawerOpen(true)}>
              添加成员
            </Button>
          ) : null
        }
      >
        <Flex vertical gap={16}>
          {notice === null || notice.kind === 'session' ? null : (
            <Alert
              type={notice.kind === 'changed' || notice.kind === 'unknown-result' ? 'warning' : 'error'}
              showIcon
              title={notice.message}
              closable={{ onClose: () => setNotice(null) }}
            />
          )}
          {membersError ? <Alert type="error" showIcon title={membersError} /> : null}
          {membersLoading ? <InitialLoading label="正在读取成员" rows={2} /> : null}
          {membersUnavailable ? (
            <Typography.Text type="secondary">成员信息不可用。</Typography.Text>
          ) : null}
          {!membersLoading && !membersUnavailable && !membersError ? (
            <ItemList
              label="团队成员"
              emptyText="暂无团队成员。"
              items={members.map((member) => ({
                key: `${member.user_id}-${member.role_key}`,
                content: (
                  <Flex justify="space-between" align="center" wrap gap={8}>
                    <Flex vertical>
                      <Typography.Text strong>{member.display_name}</Typography.Text>
                      <Typography.Text type="secondary">
                        <span>{roleLabelForCaseMember(member.role_key, roleOptions)}</span>
                        {' · '}加入于 {formatDateTime(member.joined_at)}
                      </Typography.Text>
                    </Flex>
                    {canManage ? (
                      <Button
                        danger
                        icon={<DeleteOutlined aria-hidden />}
                        aria-label={`移除成员 ${member.display_name}（${roleLabelForCaseMember(member.role_key, roleOptions)}）`}
                        loading={removingKey === `${member.user_id}:${member.role_key}`}
                        disabled={removingKey !== null}
                        onClick={() => confirmRemove(member)}
                      >
                        移除
                      </Button>
                    ) : null}
                  </Flex>
                ),
              }))}
            />
          ) : null}
          {canManage ? null : (
            <Typography.Text type="secondary" role="status">
              当前审查场景不支持团队管理。
            </Typography.Text>
          )}
        </Flex>
      </Card>
      {canManage ? (
        <AddMemberDrawer
          open={drawerOpen}
          reviewCase={reviewCase}
          roleOptions={roleOptions}
          onClose={() => setDrawerOpen(false)}
          onAdded={() => {
            setDrawerOpen(false)
            void message.success('已添加成员')
            onTeamChanged()
          }}
          onTeamChanged={onTeamChanged}
          onAccessLost={onAccessLost}
        />
      ) : null}
    </section>
  )
}
