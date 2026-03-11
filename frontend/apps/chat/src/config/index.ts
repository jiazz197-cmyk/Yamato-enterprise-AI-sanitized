/**
 * 应用配置
 * 所有配置都从环境变量读取，禁止硬编码
 */

interface AppConfig {
  port: number
  apiBaseUrl: string
  chatApiKey: string
  env: string
  userName?: string
  userAvatarUrl?: string
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

  const chatApiKey = import.meta.env.VITE_CHAT_API_KEY
  if (!chatApiKey) {
    throw new Error('VITE_CHAT_API_KEY is required in .env file')
  }

  return {
    port: portNumber,
    apiBaseUrl,
    chatApiKey,
    env: import.meta.env.VITE_ENV || import.meta.env.MODE,
    userName: import.meta.env.VITE_USER_NAME,
    userAvatarUrl: import.meta.env.VITE_USER_AVATAR_URL,
  }
}

export const config = getConfig()
