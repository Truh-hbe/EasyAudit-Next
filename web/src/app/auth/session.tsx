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
  ApiError,
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

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'resolving' })
  const [resolutionError, setResolutionError] = useState<string | null>(null)

  const clearLocalSession = useCallback(() => {
    setState({ status: 'anonymous' })
    setResolutionError(null)
  }, [])

  const refresh = useCallback(async (): Promise<SessionState> => {
    setState({ status: 'resolving' })
    setResolutionError(null)
    try {
      const next = await resolveServerSession()
      setState(next)
      return next
    } catch (error) {
      setResolutionError(
        error instanceof Error ? error.message : 'Unable to resolve server session',
      )
      throw error
    }
  }, [])

  useEffect(
    () => installSessionUnauthorizedHandler(clearLocalSession),
    [clearLocalSession],
  )

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    void resolveServerSession(controller.signal)
      .then((next) => {
        if (active) {
          setState(next)
          setResolutionError(null)
        }
      })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === 'AbortError')) {
          setResolutionError(
            error instanceof Error ? error.message : 'Unable to resolve server session',
          )
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
