import { config } from '../config'
import { apiRequest } from './api'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface MeResponse {
  id: number
  username: string
  name: string
  email: string | null
  phone: string | null
  department: string | null
  avatar: string | null
  is_active: boolean
  roles: string[]
}

export const login = (payload: LoginRequest): Promise<LoginResponse> => {
  return apiRequest<LoginResponse>(config.loginEndpoint, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export const getMe = (): Promise<MeResponse> => {
  return apiRequest<MeResponse>(config.meEndpoint)
}

