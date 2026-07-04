<template>
  <div class="auth-page">
    <div class="auth-bg-shapes">
      <div class="shape shape-1"></div>
      <div class="shape shape-2"></div>
      <div class="shape shape-3"></div>
    </div>
    <div class="auth-card">
      <div class="auth-brand">
        <div class="auth-logo">
          <el-icon><DataAnalysis /></el-icon>
        </div>
        <h2><slot name="title">DataLens</slot></h2>
        <p v-if="$slots.subtitle" class="auth-subtitle"><slot name="subtitle"></slot></p>
      </div>
      <slot></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { DataAnalysis } from '@element-plus/icons-vue'
</script>

<style scoped>
.auth-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
  position: relative;
  overflow: hidden;
  padding: 20px;
}

.auth-bg-shapes .shape {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  pointer-events: none;
}

.shape-1 {
  width: 460px;
  height: 460px;
  background: var(--brand-primary);
  opacity: 0.35;
  top: -120px;
  left: -120px;
}

.shape-2 {
  width: 340px;
  height: 340px;
  background: var(--brand-primary-light-3);
  opacity: 0.25;
  bottom: -80px;
  right: 8%;
}

.shape-3 {
  width: 240px;
  height: 240px;
  background: var(--brand-accent);
  opacity: 0.15;
  top: 40%;
  right: 28%;
}

.auth-card {
  position: relative;
  width: 420px;
  padding: 44px 40px 36px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-radius: var(--brand-radius-lg);
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.35);
  z-index: 1;
}

.auth-brand {
  text-align: center;
  margin-bottom: 32px;
}

.auth-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: linear-gradient(135deg, var(--brand-primary), var(--brand-primary-light-3));
  color: #ffffff;
  font-size: 32px;
  margin-bottom: 16px;
  box-shadow: 0 8px 24px rgba(79, 70, 229, 0.35);
}

.auth-brand h2 {
  font-size: 26px;
  font-weight: 700;
  color: var(--brand-text-primary);
  margin-bottom: 6px;
  letter-spacing: -0.02em;
}

.auth-subtitle {
  font-size: 14px;
  color: var(--brand-text-tertiary);
}

.auth-card :deep(.el-form-item) {
  margin-bottom: 20px;
}

.auth-card :deep(.el-button--primary) {
  width: 100%;
  height: 46px;
  font-weight: 600;
  font-size: 15px;
  border-radius: var(--brand-radius-md);
  background: var(--brand-primary);
  border-color: var(--brand-primary);
  transition: transform 0.2s, box-shadow 0.2s, background 0.2s;
}

.auth-card :deep(.el-button--primary:hover) {
  transform: translateY(-1px);
  background: var(--brand-primary-hover);
  border-color: var(--brand-primary-hover);
  box-shadow: var(--brand-shadow-primary);
}

.link-row {
  text-align: center;
  font-size: 14px;
  color: var(--brand-text-tertiary);
  margin-top: 4px;
}
</style>
