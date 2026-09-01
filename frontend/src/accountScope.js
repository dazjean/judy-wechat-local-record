const KEY = "judy_view_account_id";

export function getViewingAccountId() {
  const raw = sessionStorage.getItem(KEY);
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function setViewingAccountId(id) {
  if (id) sessionStorage.setItem(KEY, String(id));
  else sessionStorage.removeItem(KEY);
}
