<template>
  <div class="input-wrapper">
    <textarea
      v-if="multiline"
      :class="['input', 'input--multiline', { 'input--disabled': disabled }]"
      :placeholder="placeholder"
      :value="modelValue"
      :disabled="disabled"
      :rows="rows"
      @input="handleInput"
      @keydown.enter.exact="handleEnter"
    ></textarea>
    <input
      v-else
      :class="['input', { 'input--disabled': disabled }]"
      :type="type"
      :placeholder="placeholder"
      :value="modelValue"
      :disabled="disabled"
      @input="handleInput"
      @keydown.enter="handleEnter"
    />
  </div>
</template>

<script setup lang="ts">
interface Props {
  modelValue: string
  type?: string
  placeholder?: string
  disabled?: boolean
  multiline?: boolean
  rows?: number
}

withDefaults(defineProps<Props>(), {
  type: 'text',
  placeholder: '',
  disabled: false,
  multiline: false,
  rows: 1,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  enter: []
}>()

const handleInput = (event: Event) => {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement
  emit('update:modelValue', target.value)
}

const handleEnter = (event: KeyboardEvent) => {
  emit('enter')
}
</script>

<style lang="scss" scoped>
.input-wrapper {
  width: 100%;
}

.input {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid #dadce0;
  border-radius: 24px;
  font-size: 16px;
  outline: none;
  transition: all 0.2s ease;
  background: transparent;

  &:focus {
    border-color: #4285f4;
    box-shadow: 0 0 0 3px rgba(66, 133, 244, 0.1);
  }

  &--disabled {
    background: #f5f5f5;
    cursor: not-allowed;
    opacity: 0.6;
  }

  &--multiline {
    resize: none;
    font-family: inherit;
    line-height: 1.5;
    max-height: calc(1.5em * 5 + 24px); /* 5行 + padding */
    overflow-y: auto;
    
    /* 隐藏滚动条调整按钮 */
    &::-webkit-resizer {
      display: none;
    }
    
    /* 隐藏滚动条按钮（箭头） */
    &::-webkit-scrollbar-button {
      display: none;
    }
  }

  &::placeholder {
    color: #9aa0a6;
  }
}
</style>
