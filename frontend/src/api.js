import axios from "axios";
import { getViewingAccountId } from "./accountScope";

const http = axios.create({ baseURL: "/api", timeout: 60000 });

const SCOPED = [
  "/conversations",
  "/radar",
  "/messages",
  "/exports",
  "/jobs/rule-scan",
  "/jobs/analysis",
  "/metrics/",
  "/hits",
  "/groups",
  "/analysis/",
];

function shouldScope(url) {
  const path = String(url || "");
  return SCOPED.some((prefix) => path.includes(prefix));
}

http.interceptors.request.use((config) => {
  const id = getViewingAccountId();
  if (!id || !shouldScope(config.url)) return config;
  config.params = { ...(config.params || {}), account_id: config.params?.account_id ?? id };
  const method = (config.method || "get").toLowerCase();
  if (method === "post" && String(config.url || "").includes("/jobs/analysis")) {
    const data = config.data && typeof config.data === "object" ? config.data : {};
    if (data.account_id == null) config.data = { ...data, account_id: id };
  }
  return config;
});

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const data = err.response?.data;
    const msg = data?.message || err.message || "请求失败";
    const error = new Error(msg);
    error.code = data?.code || err.code || "";
    error.network = !err.response;
    return Promise.reject(error);
  }
);

function filenameFromHeader(header) {
  if (!header) return "";
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].replace(/"/g, "").trim());
    } catch {
      return star[1];
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : "";
}

export const api = {
  health: () => http.get("/health").then((r) => r.data),
  ping: () => http.get("/health", { timeout: 2000 }).then((r) => r.data),
  license: () => http.get("/license").then((r) => r.data),
  settings: () => http.get("/settings").then((r) => r.data),
  saveSettings: (body) => http.put("/settings", body).then((r) => r.data),
  revealData: () => http.post("/settings/reveal-data").then((r) => r.data),
  restart: () => http.post("/restart").then((r) => r.data),
  lexicon: () => http.get("/lexicon").then((r) => r.data),
  addLexicon: (body) => http.post("/lexicon", body).then((r) => r.data),
  patchLexicon: (id, body) => http.patch(`/lexicon/${id}`, body).then((r) => r.data),
  accounts: () => http.get("/accounts").then((r) => r.data),
  readerStatus: () => http.get("/wechat/status").then((r) => r.data),
  startSync: (body) => http.post("/wechat/sync", body).then((r) => r.data),
  syncJobs: () => http.get("/wechat/sync", { params: { t: Date.now() } }).then((r) => r.data),
  resetData: () => http.post("/data/reset").then((r) => r.data),
  syncJob: (id) =>
    http.get(`/wechat/sync/${id}`, { params: { t: Date.now() }, headers: { "Cache-Control": "no-cache" } }).then((r) => r.data),
  conversations: (params) => http.get("/conversations", { params }).then((r) => r.data),
  conversation: (id) => http.get(`/conversations/${id}`).then((r) => r.data),
  messages: (id) => http.get(`/conversations/${id}/messages`).then((r) => r.data),
  dailyMessages: (params) => http.get("/conversations/daily/messages", { params }).then((r) => r.data),
  exportXlsx: (params) =>
    http.post("/exports", null, { params, responseType: "blob" }).then((r) => ({
      blob: r.data,
      filename: filenameFromHeader(r.headers["content-disposition"]),
    })),
  radar: (params) => http.get("/radar", { params }).then((r) => r.data),
  overview: (params) => http.get("/metrics/overview", { params }).then((r) => r.data),
  daily: (params) => http.get("/metrics/daily", { params }).then((r) => r.data),
  hits: (params) => http.get("/hits", { params }).then((r) => r.data),
  ruleScan: () => http.post("/jobs/rule-scan").then((r) => r.data),
  startAnalysis: (body) => http.post("/jobs/analysis", body).then((r) => r.data),
  analysisJob: (id) => http.get(`/jobs/analysis/${id}`).then((r) => r.data),
  analysisResults: (params) => http.get("/analysis/results", { params }).then((r) => r.data),
  analysisResult: (id) => http.get(`/analysis/results/${id}`).then((r) => r.data),
  prompts: () => http.get("/prompts").then((r) => r.data),
  addPrompt: (body) => http.post("/prompts", body).then((r) => r.data),
  patchPrompt: (id, body) => http.patch(`/prompts/${id}`, body).then((r) => r.data),
  deletePrompt: (id) => http.delete(`/prompts/${id}`).then((r) => r.data),
  generatePrompt: (body) => http.post("/prompts/generate", body, { timeout: 120000 }).then((r) => r.data),
  groups: (params) => http.get("/groups", { params }).then((r) => r.data),
  group: (id, params) => http.get(`/groups/${id}`, { params }).then((r) => r.data),
  patchGroupMember: (id, body) => http.patch(`/groups/${id}/members`, body).then((r) => r.data),
};
