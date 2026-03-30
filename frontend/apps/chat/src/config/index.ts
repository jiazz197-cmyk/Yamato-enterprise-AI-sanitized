/**
 * 应用配置
 * 所有配置都从环境变量读取，禁止硬编码
 */

interface AppConfig {
  port: number
  apiBaseUrl: string
  env: string
  userName?: string
  userAvatarUrl?: string
  /**
   * 登录接口相对路径，例如 `/auth/login`
   */
  loginEndpoint: string
  /**
   * 获取当前用户信息的接口相对路径，例如 `/auth/me`
   */
  meEndpoint: string
  /**
   * 存储登录 Token 的 localStorage Key
   */
  authTokenStorageKey: string
  /**
   * 存储用户设置的 localStorage Key
   */
  settingsStorageKey: string
}

const getConfig = (): AppConfig => {
  const port = import.meta.env.VITE_PORT
  if (!port) {
    throw new Error('VITE_PORT is required in .env file')
  }

  const portNumber = Number(port)
  if (isNaN(portNumber) || portNumber <= 0) {
    throw new Error('VITE_PORT must be a valid positive number')
  }

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
  if (!apiBaseUrl) {
    throw new Error('VITE_API_BASE_URL is required in .env file')
  }

  const loginEndpoint = import.meta.env.VITE_LOGIN_ENDPOINT
  if (!loginEndpoint) {
    throw new Error('VITE_LOGIN_ENDPOINT is required in .env file')
  }

  const meEndpoint = import.meta.env.VITE_ME_ENDPOINT
  if (!meEndpoint) {
    throw new Error('VITE_ME_ENDPOINT is required in .env file')
  }

  const authTokenStorageKey = import.meta.env.VITE_AUTH_TOKEN_KEY
  if (!authTokenStorageKey) {
    throw new Error('VITE_AUTH_TOKEN_KEY is required in .env file')
  }

  const settingsStorageKey = import.meta.env.VITE_SETTINGS_STORAGE_KEY
  if (!settingsStorageKey) {
    throw new Error('VITE_SETTINGS_STORAGE_KEY is required in .env file')
  }

  return {
    port: portNumber,
    apiBaseUrl,
    env: import.meta.env.VITE_ENV || import.meta.env.MODE,
    userName: import.meta.env.VITE_USER_NAME,
    userAvatarUrl: import.meta.env.VITE_USER_AVATAR_URL,
    loginEndpoint,
    meEndpoint,
    authTokenStorageKey,
    settingsStorageKey,
  }
}

export const config = getConfig()
