# Yamato Frontend

基于 Monorepo 架构的前端项目，使用 Vue 3 + TypeScript + Vite 构建。

## 项目结构

```
.
├── apps/              # 应用目录
│   └── chat/         # AI 聊天应用
├── packages/          # 公共包目录
│   └── components/   # 公共组件库
└── rules/            # 项目规范文档
```

## 技术栈

- **Vue 3** - 渐进式 JavaScript 框架
- **TypeScript** - 类型安全的 JavaScript
- **Vite** - 下一代前端构建工具
- **Sass** - CSS 预处理器
- **ESLint** - 代码规范检查
- **pnpm** - 快速、节省磁盘空间的包管理器
- **Turbo** - Monorepo 构建系统

## 开发指南

### 安装依赖

```bash
pnpm install
```

### 启动开发服务器

```bash
pnpm dev
```

AI 聊天应用将在 `http://localhost:8888` 启动。

### 构建项目

```bash
pnpm build
```

### 代码检查

```bash
pnpm lint
```

### 类型检查

```bash
pnpm type-check
```

## 环境变量配置

在 `apps/chat/` 目录下创建 `.env` 文件：

```env
VITE_PORT=8888
```

参考 `apps/chat/.env.example` 文件获取更多配置选项。

## 公共组件

公共组件位于 `packages/components` 目录，包括：

- `Button` - 按钮组件
- `Input` - 输入框组件
- `Sidebar` - 侧边栏组件
- `MessageList` - 消息列表组件
- `MessageItem` - 消息项组件

## 工程规范

请参考 `rules/frontend.mdc` 了解详细的工程规范，包括：

- 禁止硬编码配置
- 使用环境变量管理配置
- 代码规范要求
