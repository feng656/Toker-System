/**
 * 平台凭据 / 浏览器代理 / 截图上传（后端 /accounts、/browser/*、/upload/screenshot）
 *
 * 已知后端缺口：
 *  - GAP-09 /upload/screenshot 只存图不识别（ocr="pending"），无 OCR 任务与人工确认流程
 *  - GAP-10 无企微推送状态与重试队列接口，线索推送结果只能由当次返回值判断
 */
import { http } from '../core/http.js';

export const platformApi = {
  status: () => http.get('/accounts/status'),
  list: () => http.get('/accounts'),
  save: (body) => http.post('/accounts', body),
  browserOpen: (platform) => http.get(`/browser/${platform}/open`),
  browserShot: (platform) => http.get(`/browser/${platform}/screenshot`),
  browserPublish: (platform, body) => http.post(`/browser/${platform}/publish`, body),
  uploadScreenshot: (kind, variantId, file) => {
    const fd = new FormData();
    fd.append('kind', kind);
    if (variantId) fd.append('variant_id', String(variantId));
    fd.append('f', file);
    return http.upload('/upload/screenshot', fd);
  },
};
