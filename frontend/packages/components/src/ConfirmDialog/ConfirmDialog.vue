<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="modelValue" class="dialog-overlay" @click="handleOverlayClick">
        <div class="dialog-container" @click.stop>
          <div class="dialog-header">
            <h3 class="dialog-title">{{ title }}</h3>
            <button
              v-if="showClose"
              class="dialog-close"
              @click="handleCancel"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
          
          <div class="dialog-body">
            <slot>
              <p class="dialog-message">{{ message }}</p>
            </slot>
          </div>
          
          <div class="dialog-footer">
            <button
              class="dialog-btn dialog-btn--cancel"
              @click="handleCancel"
            >
              {{ cancelText }}
            </button>
            <button
              class="dialog-btn dialog-btn--confirm"
              :class="{ [`dialog-btn--${type}`]: type }"
              @click="handleConfirm"
            >
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
interface Props {
  modelValue: boolean
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  showClose?: boolean
  closeOnClickOverlay?: boolean
  type?: 'primary' | 'danger' | 'warning'
}

const props = withDefaults(defineProps<Props>(), {
  title: '确认操作',
  message: '您确定要执行此操作吗？',
  confirmText: '确认',
  cancelText: '取消',
  showClose: true,
  closeOnClickOverlay: true,
  type: 'primary',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: []
  cancel: []
}>()

const handleConfirm = () => {
  emit('confirm')
  emit('update:modelValue', false)
}

const handleCancel = () => {
  emit('cancel')
  emit('update:modelValue', false)
}

const handleOverlayClick = () => {
  if (props.closeOnClickOverlay) {
    handleCancel()
  }
}
</script>

<style lang="scss" scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.dialog-container {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  min-width: 320px;
  max-width: 500px;
  width: 100%;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid #f0f0f0;
}

.dialog-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.dialog-close {
  border: none;
  background: none;
  font-size: 20px;
  color: #999;
  cursor: pointer;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.2s ease;

  &:hover {
    background-color: #f5f5f5;
    color: #666;
  }
}

.dialog-body {
  padding: 24px;
  color: #666;
  font-size: 14px;
  line-height: 1.6;
}

.dialog-message {
  margin: 0;
}

.dialog-footer {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #f0f0f0;
  justify-content: flex-end;
}

.dialog-btn {
  height: 36px;
  padding: 0 20px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  outline: none;

  &:active {
    transform: translateY(1px);
  }
}

.dialog-btn--cancel {
  background: #f5f5f5;
  color: #666;

  &:hover {
    background: #e8e8e8;
  }
}

.dialog-btn--confirm {
  color: #fff;

  &.dialog-btn--primary {
    background: #1890ff;

    &:hover {
      background: #40a9ff;
    }
  }

  &.dialog-btn--danger {
    background: #ff4d4f;

    &:hover {
      background: #ff7875;
    }
  }

  &.dialog-btn--warning {
    background: #faad14;

    &:hover {
      background: #ffc53d;
    }
  }
}

// 过渡动画
.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity 0.2s ease;

  .dialog-container {
    transition: transform 0.2s ease;
  }
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;

  .dialog-container {
    transform: scale(0.95);
  }
}
</style>
