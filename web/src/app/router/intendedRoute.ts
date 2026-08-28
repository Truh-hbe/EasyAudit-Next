export const DEFAULT_AUTHENTICATED_PATH = '/me/workbench'
export const CREDENTIAL_REMEDIATION_PATH = '/me/credential-remediation'

const ALLOWED_ROOTS = [
  '/me/workbench',
  '/me/notifications',
  '/review-cases',
  '/management',
  '/admin',
] as const

function isAllowedProductPath(pathname: string): boolean {
  return ALLOWED_ROOTS.some(
    (root) => pathname === root || pathname.startsWith(`${root}/`),
  )
}

export function safeIntendedPath(candidate: string | null): string {
  if (candidate === null || !candidate.startsWith('/') || candidate.startsWith('//')) {
    return DEFAULT_AUTHENTICATED_PATH
  }
  if (candidate.includes('\\')) {
    return DEFAULT_AUTHENTICATED_PATH
  }

  try {
    const base = new URL('https://easyaudit.invalid')
    const resolved = new URL(candidate, base)
    if (resolved.origin !== base.origin || !isAllowedProductPath(resolved.pathname)) {
      return DEFAULT_AUTHENTICATED_PATH
    }
    return `${resolved.pathname}${resolved.search}${resolved.hash}`
  } catch {
    return DEFAULT_AUTHENTICATED_PATH
  }
}
