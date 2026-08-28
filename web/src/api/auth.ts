import { publicApiRequest, sessionApiRequest } from './client'
import type {
  CurrentUserResponse,
  LoginResponse,
  PasswordChangeRequest,
} from './contracts'

export function loginWithPassword(
  loginName: string,
  password: string,
): Promise<LoginResponse> {
  return publicApiRequest<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ login_name: loginName, password }),
  })
}

export function changeOwnPassword(
  payload: PasswordChangeRequest,
): Promise<CurrentUserResponse> {
  return sessionApiRequest<CurrentUserResponse>('/api/v1/me/password', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function logoutCurrentSession(): Promise<void> {
  return sessionApiRequest<void>('/api/v1/auth/logout', { method: 'POST' })
}
