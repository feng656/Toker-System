/**
 * 素材库 / 选题池 / 合规红线（后端 /materials、/topics、/rules）
 * 说明：后端目前没有「批量导入」接口，页面只提供入口与说明，
 *      缺口记录在《接口缺口清单.md》GAP-02。
 */
import { http } from '../core/http.js';

export const materialApi = {
  list: (query) => http.get('/materials', query),
  create: (body) => http.post('/materials', body),
  update: (id, body) => http.put(`/materials/${id}`, body),
  remove: (id) => http.del(`/materials/${id}`),
  uploadFile: (id, file) => {
    const fd = new FormData();
    fd.append('f', file);
    return http.upload(`/materials/${id}/file`, fd);
  },
};

export const topicApi = {
  list: (query) => http.get('/topics', query),
  create: (body) => http.post('/topics', body),
  setStatus: (id, status) => http.put(`/topics/${id}/status`, null, { query: { status } }),
};

export const ruleApi = {
  list: () => http.get('/rules'),
  create: (body) => http.post('/rules', body),
  remove: (id) => http.del(`/rules/${id}`),
};
