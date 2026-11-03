/**
 * Vue 运行时再导出层。
 * 依赖以全局脚本方式加载（vendor/vue.global.prod.js），ES 模块无法 import CDN/全局包，
 * 这里统一从 window.Vue 取一次并按需导出，避免各模块重复写 window.Vue。
 */
const V = window.Vue;

if (!V) {
  throw new Error('Vue 未加载：请检查 web/vendor/vue.global.prod.js');
}

export const {
  createApp, ref, reactive, computed, watch, watchEffect,
  onMounted, onBeforeUnmount, onUnmounted, nextTick,
  provide, inject,
} = V;

export default V;
