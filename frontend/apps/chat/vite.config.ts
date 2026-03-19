import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const root = resolve(__dirname, '../..')

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')

  if (!env.VITE_PORT) throw new Error('VITE_PORT is required in .env file')
  if (!env.VITE_BACKEND_TARGET) throw new Error('VITE_BACKEND_TARGET is required in .env file')
  if (!env.VITE_DIFY_TARGET) throw new Error('VITE_DIFY_TARGET is required in .env file')
  if (!env.VITE_API_BASE_URL) throw new Error('VITE_API_BASE_URL is required in .env file')
  if (!env.VITE_DIFY_API_PREFIX) throw new Error('VITE_DIFY_API_PREFIX is required in .env file')

  const port = Number(env.VITE_PORT)
  if (isNaN(port) || port <= 0) throw new Error('VITE_PORT must be a valid positive number')

  const apiBase = env.VITE_API_BASE_URL // e.g. /api/v1
  const difyApiPrefix = env.VITE_DIFY_API_PREFIX // e.g. /v1

  const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

  const makeProxy = (target: string) => ({
    target,
    changeOrigin: true,
    secure: false,
    configure: (proxy: any) => {
      proxy.on('error', (err: Error, _req: any, res: any) => {
        if (res?.writeHead) {
          res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(
            JSON.stringify({
              code: 502,
              message: `Proxy target unavailable: ${target}`,
              data: err.message,
            })
          )
        }
      })
    },
  })

  return {
    plugins: [vue()],

    resolve: {
      alias: {
        '@': resolve(__dirname, './src'),
        '@yamato/components': resolve(root, './packages/components'),
      },
    },

    server: {
      port,
      host: true,

      proxy: {
        // 登录、用户等后端业务接口 → 60080（更具体的规则必须放在前面）
        [`${apiBase}/auth`]: makeProxy(env.VITE_BACKEND_TARGET),
        // 会话归档接口属于后端业务服务，不应走 Dify
        [`${apiBase}/chat-summary`]: makeProxy(env.VITE_BACKEND_TARGET),
        // 填表接口属于后端业务服务，不应走 Dify
        [`${apiBase}/closing-form`]: makeProxy(env.VITE_BACKEND_TARGET),
        // 其余 /api/v1/* → Dify 聊天服务 60086
        [apiBase]: {
          ...makeProxy(env.VITE_DIFY_TARGET),
          // 通过环境变量控制前缀改写，避免在代码中硬编码 /v1
          rewrite: (path) => path.replace(new RegExp(`^${escapeRegExp(apiBase)}`), difyApiPrefix),
        },
      },
    },
  }
})