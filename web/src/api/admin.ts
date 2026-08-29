import { sessionApiRequest } from './client'
import type { PlatformRole, UserResponse } from './contracts'

export interface OrganizationResponse {
  id: string
  name: string
  is_active: boolean
}

export interface DepartmentResponse {
  id: string
  organization_id: string
  name: string
  parent_id: string | null
  is_active: boolean
}

export interface DepartmentCreateRequest {
  name: string
  parent_id?: string | null
}

export interface DepartmentPatchRequest {
  name?: string
  parent_id?: string | null
  is_active?: boolean
}

export interface UserCreateRequest {
  display_name: string
  login_name: string
  initial_password: string
  platform_role?: PlatformRole
  primary_department_id?: string | null
  must_change_password?: boolean
}

export interface UserPatchRequest {
  display_name?: string
  platform_role?: PlatformRole
  primary_department_id?: string | null
  is_active?: boolean
}

export interface AdminScenarioVersionStatus {
  scenario_version: number
  published_at: string
  registry_present: boolean
  ready: boolean
}

export interface AdminScenarioStatusItem {
  scenario_key: string
  display_name: string
  is_active: boolean
  versions: AdminScenarioVersionStatus[]
}

export interface AdminScenarioStatusResponse {
  items: AdminScenarioStatusItem[]
}

export interface CredentialResetRequest {
  temporary_password: string
}

export function getAdminOrganization(signal?: AbortSignal): Promise<OrganizationResponse> {
  return sessionApiRequest<OrganizationResponse>('/api/v1/admin/organization', { signal })
}

export function listAdminDepartments(signal?: AbortSignal): Promise<DepartmentResponse[]> {
  return sessionApiRequest<DepartmentResponse[]>('/api/v1/admin/departments', { signal })
}

export function createAdminDepartment(
  request: DepartmentCreateRequest,
): Promise<DepartmentResponse> {
  return sessionApiRequest<DepartmentResponse>('/api/v1/admin/departments', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export function updateAdminDepartment(
  departmentId: string,
  request: DepartmentPatchRequest,
): Promise<DepartmentResponse> {
  return sessionApiRequest<DepartmentResponse>(
    `/api/v1/admin/departments/${encodeURIComponent(departmentId)}`,
    { method: 'PATCH', body: JSON.stringify(request) },
  )
}

export function listAdminUsers(signal?: AbortSignal): Promise<UserResponse[]> {
  return sessionApiRequest<UserResponse[]>('/api/v1/admin/users', { signal })
}

export function createAdminUser(request: UserCreateRequest): Promise<UserResponse> {
  return sessionApiRequest<UserResponse>('/api/v1/admin/users', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export function updateAdminUser(
  userId: string,
  request: UserPatchRequest,
): Promise<UserResponse> {
  return sessionApiRequest<UserResponse>(
    `/api/v1/admin/users/${encodeURIComponent(userId)}`,
    { method: 'PATCH', body: JSON.stringify(request) },
  )
}

export function resetAdminUserCredential(
  userId: string,
  request: CredentialResetRequest,
): Promise<UserResponse> {
  return sessionApiRequest<UserResponse>(
    `/api/v1/admin/users/${encodeURIComponent(userId)}/credential-reset`,
    { method: 'POST', body: JSON.stringify(request) },
  )
}

export function getAdminScenarioStatus(
  signal?: AbortSignal,
): Promise<AdminScenarioStatusResponse> {
  return sessionApiRequest<AdminScenarioStatusResponse>('/api/v1/admin/scenario-status', { signal })
}
