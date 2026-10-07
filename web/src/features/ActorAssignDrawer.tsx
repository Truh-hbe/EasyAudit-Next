import { Alert, Button, Drawer, Flex, Form, Grid, Input, Radio, Select, Spin, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError } from '../api/client'
import type { ActorKind, AssignmentCandidateResponse } from '../api/product'
import { FORBIDDEN_WRITE_TEXT, classifyCommandFailure, failureAlertType } from '../product/commandFailure'
import type { CommandFailure, CommandResult } from '../product/commandFailure'
import { FieldError } from '../ui/FieldError'

const SEARCH_DEBOUNCE_MS = 300
// 服务端候选接口要求 q 至少 2 个字符。
const MIN_QUERY_LENGTH = 2

export function actorKindText(actorKind: ActorKind): string {
  return actorKind === 'user' ? '用户' : '部门'
}

export interface AssignRoleOption {
  value: string
  label: string
  actorKind: ActorKind
}

interface ActorAssignDrawerProps {
  open: boolean
  onClose: () => void
  // 资源 ID：切换后丢弃已选候选人和搜索结果。
  scopeKey: string
  title: string
  roleFieldLabel: string
  actorFieldLabel: string
  okText: string
  description?: ReactNode
  // 需要原因的命令（如转交并重开）：多一个必填原因输入框；fieldName 是服务端 422 提示里的字段名。
  reason?: { label: string; fieldName: string }
  roles: readonly AssignRoleOption[]
  search: (role: AssignRoleOption, query: string, signal: AbortSignal) => Promise<AssignmentCandidateResponse[]>
  add: (role: AssignRoleOption, candidate: AssignmentCandidateResponse, reason: string) => Promise<CommandResult>
  // 候选搜索返回 403/404：资源已不可见，交给页面重新确认主授权。
  onAccessLost: () => void
}

interface FormValues {
  role: string
  actor?: { value: string; label: string }
  reason?: string
}

function candidateKey(candidate: AssignmentCandidateResponse): string {
  return `${candidate.actor_kind}:${candidate.actor_id}`
}

// 添加参与人 / 执行人：候选人只来自服务端授权的候选接口，任何失败都清空已选与结果，不保留过期名称。
export function ActorAssignDrawer({
  open,
  onClose,
  scopeKey,
  title,
  roleFieldLabel,
  actorFieldLabel,
  okText,
  description,
  reason,
  roles,
  search,
  add,
  onAccessLost,
}: ActorAssignDrawerProps) {
  const screens = Grid.useBreakpoint()
  const [form] = Form.useForm<FormValues>()
  const [candidates, setCandidates] = useState<AssignmentCandidateResponse[]>([])
  const [searching, setSearching] = useState(false)
  // 重置时重建 Select，确保下拉里不残留上一次的候选名称。
  const [selectKey, setSelectKey] = useState(0)
  const [searchedQuery, setSearchedQuery] = useState<string | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<CommandFailure | null>(null)
  const submittingRef = useRef(false)
  // 每次打开、关闭或切换资源都换一个编辑会话；晚到的结果只影响发起它的会话。
  const sessionRef = useRef(0)
  const searchRef = useRef<{ controller: AbortController; timer: number | null } | null>(null)
  const selectedRef = useRef<AssignmentCandidateResponse | null>(null)

  function cancelSearch() {
    const current = searchRef.current
    if (current === null) return
    current.controller.abort()
    if (current.timer !== null) window.clearTimeout(current.timer)
    searchRef.current = null
  }

  function resetCandidates() {
    cancelSearch()
    selectedRef.current = null
    form.setFieldValue('actor', undefined)
    setCandidates([])
    setSearching(false)
    setSearchedQuery(null)
    setSearchError(null)
    setSelectKey((key) => key + 1)
  }

  useEffect(() => {
    if (!open) return undefined
    sessionRef.current += 1
    setFailure(null)
    resetCandidates()
    return () => {
      sessionRef.current += 1
      cancelSearch()
    }
    // resetCandidates 只依赖稳定的 setter 与 form；仅在打开或切换资源时重置。
  }, [open, scopeKey])

  function runSearch(roleValue: string, query: string) {
    cancelSearch()
    const role = roles.find((option) => option.value === roleValue)
    setFailure(null)
    setSearchError(null)
    if (role === undefined || query.trim().length < MIN_QUERY_LENGTH) {
      setCandidates([])
      setSearching(false)
      setSearchedQuery(null)
      return
    }
    const controller = new AbortController()
    setSearching(true)
    const timer = window.setTimeout(() => {
      void search(role, query, controller.signal)
        .then((data) => {
          if (controller.signal.aborted) return
          setCandidates(data)
          setSearchedQuery(query)
          setSearching(false)
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          setCandidates([])
          setSearching(false)
          setSearchedQuery(null)
          selectedRef.current = null
          form.setFieldValue('actor', undefined)
          if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
            // 不显示后端 detail；用户可能仍有读权限，所以在抽屉里给出中性提示，并让页面重新确认主授权。
            setSearchError(FORBIDDEN_WRITE_TEXT)
            onAccessLost()
            return
          }
          setSearchError(error instanceof Error ? error.message : '候选搜索失败')
        })
    }, SEARCH_DEBOUNCE_MS)
    searchRef.current = { controller, timer }
  }

  async function submit(values: FormValues) {
    const candidate = selectedRef.current
    const role = roles.find((option) => option.value === values.role)
    if (candidate === null || role === undefined || submittingRef.current) return
    submittingRef.current = true
    const session = sessionRef.current
    setSubmitting(true)
    setFailure(null)
    let result: CommandResult
    try {
      result = await add(role, candidate, (values.reason ?? '').trim())
    } catch (error) {
      result = { ok: false, failure: classifyCommandFailure(error, { label: title }) }
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
    if (sessionRef.current !== session) return
    if (result.ok) {
      onClose()
      return
    }
    if (result.failure.kind === 'session' || result.failure.kind === 'busy') return
    // 授权或状态可能已变化：已选候选人作废，需要重新搜索。
    resetCandidates()
    setFailure(result.failure)
  }

  const reasonError = reason === undefined ? undefined : failure?.fieldErrors[reason.fieldName]
  const notFound = searching ? (
    <Flex align="center" gap={8}>
      <Spin size="small" />
      <span>正在查询可选人员…</span>
    </Flex>
  ) : searchedQuery === null ? (
    `请输入至少 ${MIN_QUERY_LENGTH} 个字符搜索`
  ) : (
    '没有匹配候选。'
  )

  return (
    <Drawer
      title={title}
      open={open}
      onClose={onClose}
      size={screens.sm ? 480 : '100%'}
      destroyOnHidden
      mask={{ closable: !submitting }}
      closable={!submitting}
      keyboard={!submitting}
    >
      <Form<FormValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        preserve={false}
        initialValues={{ role: roles[0]?.value }}
        disabled={submitting}
        onValuesChange={() => setFailure((current) => (current === null ? null : { ...current, fieldErrors: {} }))}
        onFinish={(values) => void submit(values)}
      >
        {description === undefined ? null : (
          <Typography.Paragraph type="secondary">{description}</Typography.Paragraph>
        )}
        {failure === null || failure.message === '' ? null : (
          <Alert type={failureAlertType(failure)} showIcon title={failure.message} style={{ marginBottom: 16 }} />
        )}
        {searchError === null ? null : (
          <Alert type="error" showIcon title={searchError} style={{ marginBottom: 16 }} />
        )}
        <Form.Item label={roleFieldLabel} name="role" rules={[{ required: true, message: `请选择${roleFieldLabel}` }]}>
          <Radio.Group
            aria-label={roleFieldLabel}
            onChange={() => resetCandidates()}
            options={roles.map((option) => ({
              value: option.value,
              label: `${option.label} · ${actorKindText(option.actorKind)}`,
            }))}
          />
        </Form.Item>
        <Form.Item label={actorFieldLabel} name="actor" rules={[{ required: true, message: `请选择${actorFieldLabel}` }]}>
          <Select
            key={selectKey}
            labelInValue
            showSearch={{
              filterOption: false,
              onSearch: (query: string) => runSearch(form.getFieldValue('role') as string, query),
            }}
            placeholder="输入至少 2 个字符搜索"
            notFoundContent={notFound}
            options={candidates.map((candidate) => ({
              value: candidateKey(candidate),
              label: candidate.display_name,
            }))}
            onSelect={(value: { value: string }) => {
              selectedRef.current = candidates.find((candidate) => candidateKey(candidate) === value.value) ?? null
            }}
          />
        </Form.Item>
        {reason === undefined ? null : (
          <Form.Item
            label={reason.label}
            name="reason"
            rules={[{ required: true, whitespace: true, message: `请填写${reason.label}` }]}
            validateStatus={reasonError === undefined ? undefined : 'error'}
            help={reasonError === undefined ? undefined : <FieldError>{reasonError}</FieldError>}
          >
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
        )}
        <Flex justify="flex-end" gap={8}>
          <Button onClick={onClose} disabled={submitting}>取消</Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {okText}
          </Button>
        </Flex>
      </Form>
    </Drawer>
  )
}
