import { Navigate, useLocation, useSearchParams } from 'react-router'

import { CredentialRemediationPage } from './app/auth/CredentialRemediationPage'
import { LoginPage } from './app/auth/LoginPage'
import { useSession } from './app/auth/session'
import {
  CREDENTIAL_REMEDIATION_PATH,
  safeIntendedPath,
} from './app/router/intendedRoute'
import { ProductShell } from './app/shell/ProductShell'

function ResolvingPage() {
  const { resolutionError, refresh } = useSession()
  return (
    <main className="foundation" aria-labelledby="resolving-title">
      <h1 id="resolving-title">正在确认服务器会话</h1>
      <p>受保护界面会在服务器 Session 与凭据状态确认后再决定是否呈现。</p>
      {resolutionError === null ? null : (
        <div role="alert">
          <p>{resolutionError}</p>
          <button type="button" onClick={() => void refresh()}>
            重试
          </button>
        </div>
      )}
    </main>
  )
}

function intendedFromCurrentLocation(pathname: string, search: string, hash: string): string {
  return safeIntendedPath(`${pathname}${search}${hash}`)
}

export function App() {
  const { state } = useSession()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const requestedNext = safeIntendedPath(searchParams.get('next'))

  if (state.status === 'resolving') {
    return <ResolvingPage />
  }

  if (state.status === 'anonymous') {
    if (location.pathname === '/login') {
      return <LoginPage />
    }
    const next = intendedFromCurrentLocation(
      location.pathname,
      location.search,
      location.hash,
    )
    return <Navigate replace to={`/login?next=${encodeURIComponent(next)}`} />
  }

  if (state.user.must_change_password) {
    if (location.pathname === CREDENTIAL_REMEDIATION_PATH) {
      return <CredentialRemediationPage />
    }
    const next =
      location.pathname === '/login'
        ? requestedNext
        : intendedFromCurrentLocation(location.pathname, location.search, location.hash)
    return (
      <Navigate
        replace
        to={`${CREDENTIAL_REMEDIATION_PATH}?next=${encodeURIComponent(next)}`}
      />
    )
  }

  if (
    location.pathname === '/login' ||
    location.pathname === CREDENTIAL_REMEDIATION_PATH
  ) {
    return <Navigate replace to={requestedNext} />
  }

  return <ProductShell />
}
