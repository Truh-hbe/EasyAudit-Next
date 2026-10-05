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
  // 添加请求的结果交给面板（按活动隔离）呈现；inSession 表示发起请求的编辑会话仍是当前会话。
  onOutcome: (outcome: AddOutcome, commandCaseId: string, inSession: boolean) => void
  onAccessLost: () => void
}

type AddOutcome = { ok: true } | { ok: false; failure: TeamFailure }

interface AddMemberFormValues {
  roleKey: string
  member?: { value: string; label: string }
}

function AddMemberDrawer({
  open,
  reviewCase,
  roleOptions,
  onClose,
  onOutcome,
  onAccessLost,
}: AddMemberDrawerProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<AddMemberFormValues>()
  const [candidates, setCandidates] = useState<CaseMemberCandidateResponse[]>([])
  const [searching, setSearching] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<TeamFailure | null>(null)
  // 写锁独立于 Drawer 的开关：关闭/重开不会释放未完成的写请求，只有该请求结束时才释放。
  const submittingRef = useRef(false)
  // 每次打开、关闭或切换审查活动都会换一个编辑会话；晚到的写结果只影响发起它的会话。
  const sessionRef = useRef(0)
  const caseIdRef = useRef(reviewCase.id)
  caseIdRef.current = reviewCase.id
  const searchRef = useRef<{ controller: AbortController; timer: number | null } | null>(null)
  // 搜索代次：每次取消或发起新搜索都递增，晚到的响应只在代次仍相同时才能写入状态。
  const searchGenerationRef = useRef(0)

  function cancelSearch() {
    searchGenerationRef.current += 1
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
    const generation = searchGenerationRef.current
    const isStale = () => controller.signal.aborted || searchGenerationRef.current !== generation
    setSearching(true)
    setError(null)
    const timer = window.setTimeout(() => {
      void searchReviewCaseMemberCandidates(reviewCase.id, roleKey, query, controller.signal)
        .then((data) => {
          if (isStale()) return
          setCandidates(data)
          setSearching(false)
        })
        .catch((failure: unknown) => {
          if (isStale()) return
          setCandidates([])
          setSearching(false)
          const classified = classifyTeamFailure(failure, 'search')
          // 授权失败后不保留已选候选人的姓名（labelInValue 把姓名存在表单里）。
          form.setFieldValue('member', undefined)
          setError(classified)
          if (classified.kind === 'gone') onAccessLost()
        })
    }, delay)
    searchRef.current = { controller, timer }
  }

  useEffect(() => {
    if (!open) return undefined
    sessionRef.current += 1
    setCandidates([])
    setError(null)
    // 重开时表单整体重置（Form preserve={false}），搜索也用同一个默认角色。
    runSearch(roleOptions[0]?.roleKey ?? '', '', 0)
    return () => {
      sessionRef.current += 1
      cancelSearch()
      setCandidates([])
      setSearching(false)
    }
    // runSearch 只依赖 reviewCase.id 与稳定的 setter；仅在打开/切换活动时重新取候选。
  }, [open, reviewCase.id, roleOptions])

  async function submit(values: AddMemberFormValues) {
    if (values.member === undefined || submittingRef.current) return
    submittingRef.current = true
    // 提交前取消在途搜索，避免它在提交结果之后把候选人写回来。
    cancelSearch()
    setSearching(false)
    const session = sessionRef.current
    const commandCaseId = reviewCase.id
    const isCurrentSession = () => sessionRef.current === session
    setSubmitting(true)
    setError(null)
    let outcome: AddOutcome
    try {
      await addReviewCaseMember(commandCaseId, values.member.value, values.roleKey)
      outcome = { ok: true }
    } catch (failure: unknown) {
      outcome = { ok: false, failure: classifyTeamFailure(failure, 'add') }
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
    const inSession = isCurrentSession()
    if (!outcome.ok && outcome.failure.kind !== 'gone' && caseIdRef.current === commandCaseId) {
      // 403 说明同一审查活动的权限已变化：不论发起请求的编辑会话是否还在，当前所有会话的候选搜索、
      // 候选人和已选姓名都要失效。其余失败只影响发起它的会话。
      if (inSession || outcome.failure.kind === 'forbidden') {
        cancelSearch()
        setSearching(false)
        setCandidates([])
        form.setFieldValue('member', undefined)
      }
      if (inSession) setError(outcome.failure)
    }
    onOutcome(outcome, commandCaseId, inSession)
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
        preserve={false}
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
  const mountedRef = useRef(true)
  const caseIdRef = useRef(reviewCase.id)
  caseIdRef.current = reviewCase.id
  // modal.confirm 由全局 App 持有，不会随面板卸载；必须自己销毁，否则确认框会带着旧活动的闭包残留。
  const confirmRef = useRef<{ destroy: () => void } | null>(null)

  function destroyConfirm() {
    confirmRef.current?.destroy()
    confirmRef.current = null
  }

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      destroyConfirm()
    }
  }, [])

  // 切换审查活动时丢弃上一个活动的弹层、确认框与提示。
  useEffect(() => {
    setDrawerOpen(false)
    setNotice(null)
    destroyConfirm()
  }, [reviewCase.id])

  // 添加结果按活动隔离、与 Drawer 的开关无关：Drawer 关闭或重开后，当前活动的写结果仍在面板上呈现。
  function handleAddOutcome(outcome: AddOutcome, commandCaseId: string, inSession: boolean) {
    if (!mountedRef.current || caseIdRef.current !== commandCaseId) return
    if (outcome.ok) {
      if (inSession) setDrawerOpen(false)
      void message.success('已添加成员')
      onTeamChanged()
      return
    }
    const { failure } = outcome
    if (failure.kind === 'gone') {
      onAccessLost()
      return
    }
    // 会话仍在 Drawer 内时，Drawer 自己显示这条失败；否则由面板显示，避免同一失败出现两次。
    if (!inSession) setNotice(failure)
    // 冲突或结果未知：写请求不自动重放，只重新读取团队供用户核对。
    if (failure.kind === 'changed' || failure.kind === 'unknown-result') onTeamChanged()
  }

  async function removeMember(member: CaseMemberViewResponse, commandCaseId: string) {
    // 当前面板必须仍属于打开确认框时的审查活动，否则不发请求。
    const isCurrent = () => mountedRef.current && caseIdRef.current === commandCaseId
    if (!isCurrent() || removingRef.current) return
    removingRef.current = true
    setRemovingKey(`${member.user_id}:${member.role_key}`)
    setNotice(null)
    try {
      await removeReviewCaseMember(commandCaseId, member.user_id, member.role_key)
      if (!isCurrent()) return
      void message.success('已移除成员')
      onTeamChanged()
    } catch (error: unknown) {
      if (!isCurrent()) return
      const failure = classifyTeamFailure(error, 'remove')
      if (failure.kind === 'gone' || failure.kind === 'forbidden') {
        destroyConfirm()
      }
      if (failure.kind === 'gone') {
        onAccessLost()
      } else {
        // 失败时不改动已渲染的成员；冲突或结果未知时重新读取，由用户核对后再决定。
        setNotice(failure)
        if (failure.kind === 'changed' || failure.kind === 'unknown-result') onTeamChanged()
      }
    } finally {
      removingRef.current = false
      if (mountedRef.current) setRemovingKey(null)
    }
  }

  function confirmRemove(member: CaseMemberViewResponse) {
    const commandCaseId = reviewCase.id
    destroyConfirm()
    confirmRef.current = modal.confirm({
      title: '移除成员',
      content: `将 ${member.display_name}（${roleLabelForCaseMember(member.role_key, roleOptions)}）从审查团队中移除。`,
      okText: '确认移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      // 失败由面板内的提示呈现，这里总是正常结束以关闭确认框。
      onOk: () => removeMember(member, commandCaseId),
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
          onOutcome={handleAddOutcome}
          onAccessLost={onAccessLost}
        />
      ) : null}
    </section>
  )
}
