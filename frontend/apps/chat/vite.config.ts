import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const root = resolve(__dirname, '../..')

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  
  // 从环境变量读取端口，必须配置
  if (!env.VITE_PORT) {
    throw new Error('VITE_PORT is required in .env file. Please check apps/chat/.env')
  }
  
  const port = Number(env.VITE_PORT)
  if (isNaN(port) || port <= 0) {
    throw new Error('VITE_PORT must be a valid positive number')
  }
  
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
    },
  }
})
