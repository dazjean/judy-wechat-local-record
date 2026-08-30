function pad(n) {
  return String(n).padStart(2, "0");
}

function parseTime(value) {
  if (value == null || value === "") return null;
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value;
  const raw = String(value).trim();
  if (/^\d{8}$/.test(raw)) {
    const y = Number(raw.slice(0, 4));
    const m = Number(raw.slice(4, 6));
    const d = Number(raw.slice(6, 8));
    return new Date(y, m - 1, d, 0, 0, 0);
  }
  const iso = raw.includes("T") ? raw : raw.replace(" ", "T");
  const dt = new Date(iso);
  if (!Number.isNaN(dt.getTime())) return dt;
  return null;
}

/** 2026年08月29日 16.28.05 */
export function formatTime(value) {
  const dt = parseTime(value);
  if (!dt) return "—";
  return `${formatDate(value)} ${pad(dt.getHours())}.${pad(dt.getMinutes())}.${pad(dt.getSeconds())}`;
}

/** 2026年08月29日 */
export function formatDate(value) {
  const dt = parseTime(value);
  if (!dt) return "—";
  return `${dt.getFullYear()}年${pad(dt.getMonth() + 1)}月${pad(dt.getDate())}日`;
}

/** YYYY-MM-DD，给日期筛选器用 */
export function toIsoDate(value) {
  const dt = parseTime(value);
  if (!dt) return "";
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
}
