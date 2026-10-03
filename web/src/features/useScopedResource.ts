import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'

export type ResourceState<T> =
  | { status: 'loading' }
  | { status: 'unavailable' }
  | { status: 'error'; message: string }
  // refreshing：已有内容在后台重新读取；refreshError：重新读取失败，仍显示的是上一次读到的内容。
  | { status: 'ready'; data: T; refreshing: boolean; refreshError: string | null }

export const LOADING: ResourceState<never> = { status: 'loading' }

export function isUnavailable(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404)
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

interface Stored<T> {
  scope: string
  state: ResourceState<T>
}

// 按作用域（资源 ID）读取一个资源：
// - scope 为 null 时不读取（主资源尚未授权，不发从属请求）；
// - 切换 scope 立即回到 loading，不显示上一个资源的内容；
// - 同一 scope 下 revision 变化只在后台刷新，保留旧内容；403/404 立即移除内容，其他失败保留旧内容并标记。
export function useScopedResource<T>(
  scope: string | null,
  revision: number,
  load: (signal: AbortSignal) => Promise<T>,
  fallbackMessage: string,
): ResourceState<T> {
  const [stored, setStored] = useState<Stored<T> | null>(null)
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    if (scope === null) return undefined
    const controller = new AbortController()
    setStored((current) =>
      current !== null && current.scope === scope && current.state.status === 'ready'
        ? { scope, state: { ...current.state, refreshing: true } }
        : { scope, state: LOADING },
    )
    void loadRef
      .current(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setStored({ scope, state: { status: 'ready', data, refreshing: false, refreshError: null } })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setStored((current) => {
          if (isUnavailable(error)) return { scope, state: { status: 'unavailable' } }
          if (current !== null && current.scope === scope && current.state.status === 'ready') {
            return {
              scope,
              state: { ...current.state, refreshing: false, refreshError: messageOf(error, fallbackMessage) },
            }
          }
          return { scope, state: { status: 'error', message: messageOf(error, fallbackMessage) } }
        })
      })
    return () => controller.abort()
  }, [scope, revision, fallbackMessage])

  return scope !== null && stored !== null && stored.scope === scope ? stored.state : LOADING
}
