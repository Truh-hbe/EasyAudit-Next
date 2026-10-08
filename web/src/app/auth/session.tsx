import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import {
  advanceSessionGeneration,
  ApiError,
  currentSessionGeneration,
  installSessionUnauthorizedHandler,
  sessionApiRequest,
} from '../../api/client'
import type { CurrentUserResponse } from '../../api/contracts'

export type SessionState =
  | { status: 'resolving' }
  | { status: 'anonymous' }
  | { status: 'authenticated'; user: CurrentUserResponse }

interface SessionContextValue {
  state: SessionState
  resolutionError: string | null
  refresh: () => Promise<SessionState>
  clearLocalSession: () => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export async function resolveServerSession(
  signal?: AbortSignal,
): Promise<SessionState> {
  try {
    const user = await sessionApiRequest<CurrentUserResponse>('/api/v1/me', { signal })
    return { status: 'authenticated', user }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return { status: 'anonymous' }
    }
    throw error
  }
}

// 只显示固定中文，不透传后端 detail 或 fetch 的英文错误原文。
export function resolutionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 503
      ? '服务器暂不可用，请稍后重试。'
      : `无法确认登录状态（状态码 ${error.status}），请重试。`
  }
  return '无法连接到服务器，请检查网络后重试。'
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'resolving' })
  const [resolutionError, setResolutionError] = useState<string | null>(null)

  const clearLocalSession = useCallback(() => {
    advanceSessionGeneration()
    setState({ status: 'anonymous' })
    setResolutionError(null)
  }, [])

  const refresh = useCallback(async (): Promise<SessionState> => {
    const generation = advanceSessionGeneration()
    setState({ status: 'resolving' })
    setResolutionError(null)
    try {
      const next = await resolveServerSession()
      if (currentSessionGeneration() === generation) {
        setState(next)
      }
      return next
    } catch (error) {
      if (currentSessionGeneration() === generation) {
        setResolutionError(resolutionErrorMessage(error))
      }
      throw error
    }
  }, [])

  useEffect(
    () => installSessionUnauthorizedHandler(clearLocalSession),
    [clearLocalSession],
  )

  useEffect(() => {
    const controller = new AbortController()
    const generation = currentSessionGeneration()
    let active = true

    void resolveServerSession(controller.signal)
      .then((next) => {
        if (active && currentSessionGeneration() === generation) {
          setState(next)
          setResolutionError(null)
        }
      })
      .catch((error: unknown) => {
        if (
          active &&
          currentSessionGeneration() === generation &&
          !(error instanceof DOMException && error.name === 'AbortError')
        ) {
          setResolutionError(resolutionErrorMessage(error))
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [])

  const value = useMemo(
    () => ({ state, resolutionError, refresh, clearLocalSession }),
    [clearLocalSession, refresh, resolutionError, state],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext)
  if (value === null) {
    throw new Error('useSession must be used within SessionProvider')
  }
  return value
}
