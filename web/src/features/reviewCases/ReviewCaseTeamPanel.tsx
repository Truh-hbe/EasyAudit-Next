import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

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

interface ReviewCaseTeamPanelProps {
  reviewCase: ReviewCaseResponse
  roleOptions: readonly ScenarioCaseRoleOption[]
  members: CaseMemberViewResponse[]
  membersLoading: boolean
  membersUnavailable: boolean
  membersError: string | null
  onTeamChanged: () => void
}

export function roleLabelForCaseMember(
  roleKey: string,
  roleOptions: readonly ScenarioCaseRoleOption[],
): string {
  return roleOptions.find((option) => option.roleKey === roleKey)?.label ?? roleKey
}

export function teamMutationErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status === 403) {
    return '当前用户没有管理审查团队的权限。'
  }
  if (error instanceof ApiError && error.status === 409) {
    return '团队状态发生冲突，请刷新后重试。'
  }
  return error instanceof Error ? error.message : fallback
}

export function ReviewCaseTeamPanel({
  reviewCase,
  roleOptions,
  members,
  membersLoading,
  membersUnavailable,
  membersError,
  onTeamChanged,
}: ReviewCaseTeamPanelProps) {
  const [roleKey, setRoleKey] = useState(roleOptions[0]?.roleKey ?? '')
  const [query, setQuery] = useState('')
  const [candidates, setCandidates] = useState<CaseMemberCandidateResponse[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [mutationError, setMutationError] = useState<string | null>(null)

  useEffect(() => {
    setRoleKey((current) =>
      roleOptions.some((option) => option.roleKey === current)
        ? current
        : (roleOptions[0]?.roleKey ?? ''),
    )
    setCandidates([])
    setSearchError(null)
  }, [roleOptions])

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!roleKey) return
    setSearching(true)
    setSearchError(null)
    setCandidates([])
    try {
      setCandidates(
        await searchReviewCaseMemberCandidates(reviewCase.id, roleKey, query),
      )
    } catch (error: unknown) {
      // Do not retain stale names after an authorization or network failure.
      setCandidates([])
      setSearchError(teamMutationErrorMessage(error, '候选成员请求失败'))
    } finally {
      setSearching(false)
    }
  }

  async function addCandidate(candidate: CaseMemberCandidateResponse) {
    const key = `add:${candidate.user_id}:${roleKey}`
    setBusyKey(key)
    setMutationError(null)
    try {
      await addReviewCaseMember(reviewCase.id, candidate.user_id, roleKey)
      setCandidates([])
      onTeamChanged()
    } catch (error: unknown) {
      setMutationError(teamMutationErrorMessage(error, '添加成员失败'))
    } finally {
      setBusyKey(null)
    }
  }

  async function removeMember(member: CaseMemberViewResponse) {
    const key = `remove:${member.user_id}:${member.role_key}`
    setBusyKey(key)
    setMutationError(null)
    try {
      await removeReviewCaseMember(reviewCase.id, member.user_id, member.role_key)
      onTeamChanged()
    } catch (error: unknown) {
      // In particular, a 409 must leave the rendered membership untouched.
      setMutationError(teamMutationErrorMessage(error, '移除成员失败'))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <section className="surface-card" aria-labelledby="case-team-title">
      <h2 id="case-team-title">团队管理</h2>
      {membersLoading ? <p>正在读取成员…</p> : null}
      {membersUnavailable ? <p className="empty-note">成员信息不可用。</p> : null}
      {membersError ? <p role="alert">{membersError}</p> : null}
      {!membersLoading && !membersUnavailable && !membersError && members.length === 0 ? (
        <p className="empty-note">暂无团队成员。</p>
      ) : null}
      {members.length > 0 ? (
        <ul className="surface-list">
          {members.map((member) => {
            const key = `remove:${member.user_id}:${member.role_key}`
            return (
              <li key={`${member.user_id}-${member.role_key}`}>
                <strong>{member.display_name}</strong>
                <span>{roleLabelForCaseMember(member.role_key, roleOptions)}</span>
                <span>加入于 {formatDateTime(member.joined_at)}</span>
                {roleOptions.length > 0 ? (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => void removeMember(member)}
                    disabled={busyKey !== null}
                  >
                    {busyKey === key ? '正在移除…' : '移除'}
                  </button>
                ) : null}
              </li>
            )
          })}
        </ul>
      ) : null}

      {roleOptions.length === 0 ? (
        <p role="status" className="empty-note">
          当前审查场景不支持团队管理。
        </p>
      ) : (
        <form className="command-form subsurface" onSubmit={(event) => void search(event)}>
          <h3>添加成员</h3>
          <label>
            团队角色
            <select
              value={roleKey}
              onChange={(event) => setRoleKey(event.target.value)}
              disabled={busyKey !== null}
            >
              {roleOptions.map((option) => (
                <option key={option.roleKey} value={option.roleKey}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            搜索成员
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              disabled={busyKey !== null}
              placeholder="输入姓名"
            />
          </label>
          <button type="submit" disabled={searching || busyKey !== null || !roleKey}>
            {searching ? '正在搜索…' : '搜索候选人'}
          </button>
          {searchError ? <p role="alert">{searchError}</p> : null}
          {mutationError ? <p role="alert">{mutationError}</p> : null}
          {candidates.length > 0 ? (
            <ul className="surface-list" aria-label="候选成员">
              {candidates.map((candidate) => {
                const key = `add:${candidate.user_id}:${roleKey}`
                return (
                  <li key={candidate.user_id}>
                    <strong>{candidate.display_name}</strong>
                    <button
                      type="button"
                      onClick={() => void addCandidate(candidate)}
                      disabled={busyKey !== null}
                    >
                      {busyKey === key ? '正在添加…' : '添加'}
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : null}
          {!searching && !searchError && candidates.length === 0 && query.length > 0 ? (
            <p className="empty-note">没有找到候选成员。</p>
          ) : null}
        </form>
      )}
      {mutationError && roleOptions.length === 0 ? <p role="alert">{mutationError}</p> : null}
    </section>
  )
}
