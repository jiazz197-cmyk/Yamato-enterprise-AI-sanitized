import { config } from '../config'
import { apiRequest } from './api'

const AUTH_BASE = '/auth'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface MeResponse {
  id: string
  username: string
  name: string | null
  email: string | null
  phone: string | null
  department: string | null
  avatar: string | null
  is_active: boolean
  role: string
  roles: { id: number; name: string }[]
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
  name?: string
}

export interface UserResponse {
  id: string
  username: string
  name: string | null
  email: string
  phone: string | null
  department: string | null
  avatar: string | null
  is_active: boolean
  role: string
  roles: { id: number; name: string }[]
}

export interface UpdateRoleRequest {
  role: 'admin' | 'user'
}

export const login = async (payload: LoginRequest): Promise<LoginResponse> => {
  return apiRequest<LoginResponse>(config.loginEndpoint, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export const getMe = (): Promise<MeResponse> => {
  return apiRequest<MeResponse>(config.meEndpoint)
}

export const register = (payload: RegisterRequest): Promise<UserResponse> => {
  return apiRequest<UserResponse>(`${AUTH_BASE}/register`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export const listUsers = (): Promise<UserResponse[]> => {
  return apiRequest<UserResponse[]>(`${AUTH_BASE}/users`)
}

export const deleteUser = (userId: string): Promise<void> => {
  return apiRequest<void>(`${AUTH_BASE}/users/${userId}`, {
    method: 'DELETE',
  })
}

export const updateUserRole = (userId: string, payload: UpdateRoleRequest): Promise<UserResponse> => {
  return apiRequest<UserResponse>(`${AUTH_BASE}/users/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

/**
 * Persist role in localStorage settings so App.vue can read it without
 * an additional network request on every route change.
 */
export const saveUserRole = (role: string): void => {
  try {
    const raw = localStorage.getItem(config.settingsStorageKey)
    const existing = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
    localStorage.setItem(config.settingsStorageKey, JSON.stringify({ ...existing, role }))
  } catch {
    // ignore storage errors
  }
}

export const readUserRole = (): string => {
  try {
    const raw = localStorage.getItem(config.settingsStorageKey)
    if (!raw) return ''
    const parsed = JSON.parse(raw) as { role?: unknown }
    return String(parsed.role ?? '').trim()
  } catch {
    return ''
  }
}
