/** 串行、有上限的扫码轮询。关闭/切换账号后旧异步响应不能回写新弹窗。 */
export function createQrPoller({ refresh, session, onState, onError, onLimit,
  delayMs = 3000, maxChecks = 40, maxErrors = 3,
  schedule = (fn, ms) => window.setTimeout(fn, ms), cancel = (id) => window.clearTimeout(id) }) {
  let epoch = 0;
  let timer = null;
  function stop() {
    epoch += 1;
    if (timer !== null) cancel(timer);
    timer = null;
  }
  function start(accountId) {
    stop();
    const current = epoch;
    let checks = 0;
    let errors = 0;
    async function tick() {
      if (current !== epoch) return;
      try {
        await refresh(accountId); // 必须主动查询平台；仅GET本地session不会完成扫码登录。
        if (current !== epoch) return;
        const data = await session(accountId);
        if (current !== epoch) return;
        errors = 0;
        await onState(data);
        if (current !== epoch || data.status !== 'awaiting_scan') return;
      } catch (error) {
        if (current !== epoch) return;
        errors += 1;
        if (errors >= maxErrors || [401, 403, 404, 409, 422, 503].includes(error.status)) {
          onError(error);
          return;
        }
      }
      checks += 1;
      if (checks >= maxChecks) { onLimit(); return; }
      if (current === epoch) timer = schedule(tick, delayMs);
    }
    timer = schedule(tick, delayMs);
  }
  return { start, stop };
}
