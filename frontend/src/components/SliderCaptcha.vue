<template>
  <div class="slider-captcha" :class="{ verified, shaking }">
    <!-- 轨道 -->
    <div class="slider-track" ref="trackRef">
      <!-- 进度条填充 -->
      <div class="slider-fill" :style="{ width: percent + '%' }" />
      <!-- 提示文案 -->
      <span v-if="!verified" class="slider-tip">
        {{ shaking ? '验证失败，请重试' : '向右拖动滑块完成验证' }}
      </span>
      <span v-else class="slider-tip success">验证通过</span>
      <!-- 滑块按钮 -->
      <div
        class="slider-thumb"
        :style="{ left: thumbLeft + 'px' }"
        :class="{ dragging, verified }"
        @mousedown="onStart"
        @touchstart.passive="onStart"
      >
        <el-icon v-if="!verified"><DArrowRight /></el-icon>
        <el-icon v-else><Check /></el-icon>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { Check, DArrowRight } from '@element-plus/icons-vue'

const emit = defineEmits<{ (e: 'verified'): void }>()

const trackRef = ref<HTMLElement | null>(null)
const dragging = ref(false)
const verified = ref(false)      // 是否已通过
const shaking = ref(false)       // 失败抖动

// 滑块 left（相对轨道左端，px）
const thumbLeft = ref(0)
// 轨道宽度（动态读取）
const trackWidth = ref(0)
// 拖动起点：按下时鼠标 x 和滑块 left
let startX = 0
let startLeft = 0
// 拖动轨迹：{x: 相对位移, t: 时间戳}
const trace: Array<{ x: number; t: number }> = []

const percent = computed(() => {
  if (!trackWidth.value) return 0
  // 滑块宽度 40，可移动范围 = 轨道宽 - 40
  const movable = trackWidth.value - 40
  if (movable <= 0) return 0
  return Math.min(100, (thumbLeft.value / movable) * 100)
})

function onStart(e: MouseEvent | TouchEvent) {
  if (verified.value) return
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  // 读取轨道宽度
  if (trackRef.value) {
    trackWidth.value = trackRef.value.clientWidth
  }
  startX = clientX
  startLeft = thumbLeft.value
  dragging.value = true
  // 重置轨迹
  trace.length = 0
  trace.push({ x: 0, t: Date.now() })

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onEnd)
  window.addEventListener('touchmove', onMove, { passive: false })
  window.addEventListener('touchend', onEnd)
}

function onMove(e: MouseEvent | TouchEvent) {
  if (!dragging.value) return
  // touchmove 阻止默认（防页面滚动）
  if (e.cancelable) e.preventDefault()
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  const delta = clientX - startX
  const movable = trackWidth.value - 40
  let next = startLeft + delta
  // 限制在 [0, movable]
  next = Math.max(0, Math.min(movable, next))
  thumbLeft.value = next
  trace.push({ x: next, t: Date.now() })
}

function onEnd() {
  dragging.value = false
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onEnd)
  window.removeEventListener('touchmove', onMove)
  window.removeEventListener('touchend', onEnd)

  if (verified.value) return

  // 到位判定：滑块到达右端（percent >= 95）
  if (percent.value < 95) {
    // 没拖到位，直接回弹（不算失败）
    resetThumb()
    return
  }

  // 轨迹反机器人检测
  if (isBotTrace(trace)) {
    fail()
    return
  }

  // 通过
  verified.value = true
  // 钉死在右端
  const movable = trackWidth.value - 40
  thumbLeft.value = movable
  emit('verified')
}

/**
 * 反机器人轨迹检测：
 * 1. 总耗时 < 120ms → 机器（人再快也到不了，机器瞬移是 < 50ms 零采样点）
 * 2. 采样点 < 4 → 机器（mousemove 正常拖动会触发多次，瞬移/setInterval 模拟才稀疏）
 * 3. 速度方差 ≈ 0 → 机器（完全匀速是机器特征，人即便快速匀速拖也有微小波动）
 *
 * 注意：纯前端滑块（无后端图片缺口校验）作用是"增加机器人成本"，
 * 阈值不能卡正常用户。快速拖动 ≠ 机器人——熟练用户/触屏甩动 200ms 内
 * 完成很常见，之前的 300ms + 方差 0.5 阈值会误杀快速正常用户。
 */
function isBotTrace(t: Array<{ x: number; t: number }>): boolean {
  if (t.length < 4) return true    // 采样点太少（瞬移/直接 setLeft 无中间点）
  const duration = t[t.length - 1].t - t[0].t
  if (duration < 120) return true  // 瞬移，机器特征（人再快也 > 120ms）

  // 计算相邻点速度，再看方差
  const speeds: number[] = []
  for (let i = 1; i < t.length; i++) {
    const dx = t[i].x - t[i - 1].x
    const dt = t[i].t - t[i - 1].t || 1
    speeds.push(dx / dt)
  }
  const mean = speeds.reduce((a, b) => a + b, 0) / speeds.length
  const variance = speeds.reduce((a, b) => a + (b - mean) ** 2, 0) / speeds.length
  // 完全匀速（方差≈0）判机器。阈值 0.05：人即便快速匀速拖，微观也有抖动
  return variance < 0.05
}

function fail() {
  shaking.value = true
  setTimeout(() => {
    shaking.value = false
    resetThumb()
  }, 500)  // 抖动 500ms 后重置
}

function resetThumb() {
  thumbLeft.value = 0
}

// 组件卸载时清理监听（防内存泄漏）
onUnmounted(() => {
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onEnd)
  window.removeEventListener('touchmove', onMove)
  window.removeEventListener('touchend', onEnd)
})

// 暴露重置方法（父组件登录失败时可调，强制重新验证）
defineExpose({
  reset() {
    verified.value = false
    resetThumb()
  },
})
</script>

<style scoped>
.slider-captcha {
  user-select: none;
  width: 100%;
}

.slider-track {
  position: relative;
  height: 40px;
  background: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid #dcdfe6;
}

.slider-fill {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: linear-gradient(90deg, #409eff 0%, #67c23a 100%);
  transition: width 0.1s ease;
}

/* 失败时进度条变红 */
.slider-captcha.shaking .slider-fill {
  background: #f56c6c;
}

.slider-tip {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 13px;
  color: #909399;
  pointer-events: none;
  white-space: nowrap;
}

.slider-tip.success {
  color: #fff;
}

.slider-thumb {
  position: absolute;
  top: 0;
  left: 0;
  width: 40px;
  height: 40px;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  color: #606266;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  transition: left 0.1s ease;
  z-index: 2;
}

.slider-thumb.dragging {
  cursor: grabbing;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
  /* 拖动时去掉过渡，跟手 */
  transition: none;
}

.slider-thumb.verified {
  background: #67c23a;
  border-color: #67c23a;
  color: #fff;
  cursor: default;
}

/* 失败抖动动画 */
.slider-captcha.shaking .slider-track {
  animation: shake 0.4s;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-6px); }
  40% { transform: translateX(6px); }
  60% { transform: translateX(-4px); }
  80% { transform: translateX(4px); }
}

/* 回弹动画（没拖到位松手时） */
.slider-thumb:not(.dragging) {
  transition: left 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}
</style>
