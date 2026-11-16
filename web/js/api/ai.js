/**
 * AI 能力状态（后端 /llm/status、/video/status）。
 * 只读展示是否已接入平台网关/视频服务，密钥永远不会下发到前端。
 */
import { http } from '../core/http.js';

export const aiApi = {
  llmStatus: () => http.get('/llm/status'),
  videoStatus: () => http.get('/video/status'),
};
