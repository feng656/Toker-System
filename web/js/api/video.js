/**
 * 平台视频生成（后端 /video/*）。
 *  - status：是否已配置平台视频服务及默认模型/分辨率
 *  - generate：按 variant_id 或 prompt 提交任务，202 返回 task_id；同参数幂等
 *  - task：轮询任务状态，succeeded 时 result 含 video 元信息
 *  - fileUrl+authFetch：成片走带令牌的 fetch 取 blob，避免把令牌拼进 URL
 */
import { http } from '../core/http.js';

export const videoApi = {
  status: () => http.get('/video/status'),
  generate: (body) => http.post('/video/generate', body),
  task: (id) => http.get(`/video/tasks/${id}`),
  file: (id) => http.get(`/video/tasks/${id}/file`, undefined, { raw: true, timeoutMs: 120000 }),
};
