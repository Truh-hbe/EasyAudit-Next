export type PlatformRole = 'system_admin' | 'ordinary_user'

export interface UserResponse {
  id: string
  organization_id: string
  display_name: string
  platform_role: PlatformRole
  primary_department_id: string | null
  is_active: boolean
}

export interface CurrentUserResponse extends UserResponse {
  must_change_password: boolean
}

export interface LoginResponse {
  user: UserResponse
  session_id: string
  expires_at: string
}

export interface PasswordChangeRequest {
  current_password: string
  new_password: string
}
