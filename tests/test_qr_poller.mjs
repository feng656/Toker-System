import test from 'node:test';
import assert from 'node:assert/strict';
import { createQrPoller } from '../web/js/core/qr-poller.js';

function fixture(options = {}) {
  const queue = new Map();
  const states = []; const errors = []; const calls = [];
  let serial = 0; let limits = 0;
  const poller = createQrPoller({
    refresh: async id => { calls.push(['refresh', id]); },
    session: async id => { calls.push(['session', id]); return { status: 'awaiting_scan', id }; },
    onState: data => states.push(data), onError: e => errors.push(e), onLimit: () => { limits += 1; },
    schedule: fn => { queue.set(++serial, fn); return serial; }, cancel: id => queue.delete(id),
    ...options,
  });
  async function tick() {
    const entry = queue.entries().next().value;
    assert.ok(entry, '应存在一次待执行的查询');
    queue.delete(entry[0]);
    await entry[1]();
  }
  return { poller, queue, states, errors, calls, tick, limits: () => limits };
}

test('先主动refresh，再读取session，待扫码才安排下次', async () => {
  const f = fixture(); f.poller.start(7);
  await f.tick();
  assert.deepEqual(f.calls, [['refresh', 7], ['session', 7]]);
  assert.equal(f.states[0].id, 7);
  assert.equal(f.queue.size, 1); f.poller.stop(); assert.equal(f.queue.size, 0);
});

test('已登录与过期都是终态，不再轮询', async () => {
  for (const status of ['connected', 'expired']) {
    const f = fixture({ session: async () => ({ status }) });
    f.poller.start(1); await f.tick();
    assert.equal(f.queue.size, 0); assert.equal(f.states[0].status, status);
  }
});

test('关闭弹窗后，旧在途请求不能读取或回写状态', async () => {
  let resolve;
  const f = fixture({ refresh: () => new Promise(done => { resolve = done; }) });
  f.poller.start(1); const inflight = f.tick();
  assert.equal(f.queue.size, 0); // 串行，无重叠请求
  f.poller.stop(); resolve(); await inflight;
  assert.deepEqual(f.states, []); assert.deepEqual(f.calls, []); assert.equal(f.queue.size, 0);
});

test('切换账号后旧响应不会污染新账号', async () => {
  let resolve;
  const f = fixture({ refresh: id => id === 1 ? new Promise(done => { resolve = done; }) : Promise.resolve() });
  f.poller.start(1); const old = f.tick(); f.poller.start(2); resolve(); await old;
  await f.tick(); assert.deepEqual(f.states.map(x => x.id), [2]); f.poller.stop();
});

test('轮询达到上限后暂停，不无限请求', async () => {
  const f = fixture({ maxChecks: 2 }); f.poller.start(1);
  await f.tick(); await f.tick(); assert.equal(f.limits(), 1); assert.equal(f.queue.size, 0);
});

test('网络错误连续三次才暂停，明确依赖不可用立即暂停', async () => {
  const f = fixture({ refresh: async () => { throw new Error('network'); } }); f.poller.start(1);
  await f.tick(); await f.tick(); assert.equal(f.errors.length, 0); await f.tick();
  assert.equal(f.errors.length, 1); assert.equal(f.queue.size, 0);
  const g = fixture({ refresh: async () => { throw Object.assign(new Error('not configured'), { status: 503 }); } });
  g.poller.start(2); await g.tick(); assert.equal(g.errors.length, 1); assert.equal(g.queue.size, 0);
});
