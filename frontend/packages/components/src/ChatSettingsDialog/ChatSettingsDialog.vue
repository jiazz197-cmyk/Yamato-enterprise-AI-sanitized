<template>
  <Teleport to="body">
    <Transition name="settings-fade">
      <div v-if="modelValue" class="settings-overlay">
        <div class="settings-container" @click.stop>
          <div class="settings-header">
            <h3 class="settings-title">对话设置</h3>
          </div>

          <div class="settings-body">
            <div class="settings-field">
              <label class="settings-label" for="settings-user-id">用户 ID</label>
              <input
                id="settings-user-id"
                v-model="localUserId"
                class="settings-input"
                type="text"
                placeholder="请输入用户 ID"
                @keydown.enter="handleConfirm"
              />
            </div>
            <div class="settings-field">
              <label class="settings-label" for="settings-search">搜索模式</label>
              <select id="settings-search" v-model="localSearch" class="settings-select">
                <option value="online">联网搜索</option>
                <option value="local">本地搜索</option>
                <option value="both">本地&amp;网络</option>
              </select>
            </div>
          </div>

          <div class="settings-footer">
            <button
              class="settings-btn"
              :disabled="!localUserId.trim()"
              @click="handleConfirm"
            >
              确认
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

export type SearchMode = 'online' | 'local' | 'both'

export interface ChatSettings {
  userId: string
  search: SearchMode
}

interface Props {
  modelValue: boolean
  initialSettings?: ChatSettings
}

const props = withDefaults(defineProps<Props>(), {
  initialSettings: () => ({ userId: '', search: 'online' as SearchMode }),
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [settings: ChatSettings]
}>()

const localUserId = ref(props.initialSettings.userId)
const localSearch = ref<SearchMode>(props.initialSettings.search)

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      localUserId.value = props.initialSettings.userId
      localSearch.value = props.initialSettings.search
    }
  }
)

const handleConfirm = () => {
  if (!localUserId.value.trim()) return
  emit('confirm', { userId: localUserId.value.trim(), search: localSearch.value })
  emit('update:modelValue', false)
}
</script>

<style lang="scss" scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.settings-container {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  width: 400px;
  overflow: hidden;
}

.settings-header {
  padding: 20px 24px 0;
}

.settings-title {
  font-size: 18px;
  font-weight: 600;
  color: #202124;
  margin: 0;
}

.settings-body {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.settings-label {
  font-size: 14px;
  font-weight: 500;
  color: #3c4043;
}

.settings-input,
.settings-select {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #dadce0;
  border-radius: 8px;
  font-size: 14px;
  color: #202124;
  background: #fff;
  outline: none;
  transition: border-color 0.2s;

  &:focus {
    border-color: #4285f4;
  }
}

.settings-select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none'%3E%3Cpath d='M6 9l6 6 6-6' stroke='%235f6368' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
}

.settings-footer {
  padding: 0 24px 20px;
  display: flex;
  justify-content: flex-end;
}

.settings-btn {
  height: 40px;
  padding: 0 24px;
  background: #4285f4;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;

  &:hover:not(:disabled) {
    background: #1976d2;
  }

  &:disabled {
    background: #dadce0;
    cursor: not-allowed;
  }
}

.settings-fade-enter-active,
.settings-fade-leave-active {
  transition: opacity 0.2s ease;

  .settings-container {
    transition: transform 0.2s ease;
  }
}

.settings-fade-enter-from,
.settings-fade-leave-to {
  opacity: 0;

  .settings-container {
    transform: scale(0.95);
  }
}
</style>
