<template>
  <div class="page">
    <div class="head">
      <span>会话明细</span>
      <div class="tools">
        <el-input
          v-model="q"
          clearable
          placeholder="搜索好友备注 / 昵称"
          style="width: 220px"
          @clear="reload"
          @keyup.enter="reload"
        />
        <el-select v-model="flag" clearable placeholder="全部预警" style="width: 140px" @change="reload">
          <el-option label="超时未回" value="timeout" />
          <el-option label="禁用词" value="forbidden" />
          <el-option label="缺原文件" value="missing_media" />
        </el-select>
        <el-button @click="reload">筛选</el-button>
        <el-button :loading="exporting === 'filtered'" @click="exportFile('filtered')">导出当前筛选</el-button>
        <el-button :loading="exporting === 'all'" @click="exportFile('all')">导出全部</el-button>
      </div>
    </div>
    <section class="pane list-pane">
        <div class="table-wrap">
          <el-table
            :data="items"
            row-key="id"
            height="100%"
            highlight-current-row
            :current-row-key="selectedKey"
            class="conv-table"
            @row-click="onRowClick"
          >
          <el-table-column label="好友" min-width="110">
            <template #default="{ row }">
              <div>{{ row.contact }}</div>
              <div v-if="row.contact_sub" class="sub">{{ row.contact_sub }}</div>
            </template>
          </el-table-column>
          <el-table-column label="日期" min-width="108" class-name="col-date">
            <template #default="{ row }">
              <span class="date-cell">{{ formatTableDate(row.day || row.started_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="消息数" width="72" align="right">
            <template #default="{ row }">{{ row.msg_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="照片" width="64" align="right">
            <template #default="{ row }">{{ row.image_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="文件" width="64" align="right">
            <template #default="{ row }">{{ row.file_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column min-width="220" class-name="col-warn">
            <template #header>
              <el-tooltip content="当日会话的规则预警，非微信好友标签" placement="top">
                <span class="warn-head">预警</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">
              <div class="warn-tags">
                <el-tag v-if="row.timeout" type="warning" size="small">超时未回</el-tag>
                <el-tag v-if="row.forbidden" type="danger" size="small">禁用词</el-tag>
                <el-tag v-if="row.missing_media" type="info" size="small">缺原文件</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="时段" min-width="180">
            <template #default="{ row }">{{ formatSegmentRange(row.started_at, row.last_msg_at) }}</template>
          </el-table-column>
        </el-table>
        </div>
        <el-pagination
          class="pager"
          layout="prev, pager, next, total"
          :total="total"
          :page-size="20"
          v-model:current-page="page"
          @current-change="load"
        />
      </section>

    <el-drawer
      v-model="drawerOpen"
      direction="rtl"
      size="520px"
      :with-header="false"
      class="chat-drawer"
      @closed="onDrawerClosed"
    >
      <div class="drawer-shell">
        <div class="chat-head">
          <template v-if="selected">
            <div>
              <b>{{ selected.contact || "会话" }}</b>
              <span v-if="selected.contact_sub" class="sub inline">{{ selected.contact_sub }}</span>
              <span class="t">{{ selected.msg_count || messages.length }} 条</span>
              <span v-if="selected.segment_count > 1" class="t">· {{ selected.segment_count }} 段合并</span>
            </div>
            <div class="chat-head-tags">
              <el-tag v-if="selected.timeout" type="warning" size="small">超时未回</el-tag>
              <el-tag v-if="selected.forbidden" type="danger" size="small">禁用词</el-tag>
              <el-tag v-if="selected.missing_media" type="info" size="small">缺原文件</el-tag>
            </div>
          </template>
          <span v-else class="t">会话记录</span>
        </div>
        <div ref="chatBox" class="chat-body">
          <p v-if="selectedKey && loadingChat" class="empty">正在加载…</p>
          <p v-else-if="!messages.length" class="empty">这条会话没有消息</p>
          <div
            v-for="m in messages"
            :key="m.id"
            class="bubble"
            :class="m.sender_role"
          >
            <div class="meta">
              <b>{{ m.speaker || m.sender_name || "对方" }}</b>
              <span class="t">{{ formatTime(m.msg_time) }}</span>
            </div>
            <div v-if="displayText(m)" class="body">{{ displayText(m) }}</div>
            <template v-for="card in [linkCard(m)]" :key="'link-' + m.id">
              <component
                v-if="card"
                :is="card.href ? 'a' : 'div'"
                class="link-card"
                :class="{ clickable: !!card.href }"
                :href="card.href || undefined"
                :target="card.href ? '_blank' : undefined"
                rel="noopener noreferrer"
                @click.stop
              >
                <div class="link-kicker">链接</div>
                <div class="link-title">{{ card.title }}</div>
                <div v-if="card.desc" class="link-desc">{{ card.desc }}</div>
                <div v-if="card.url" class="link-url">{{ card.url }}</div>
              </component>
            </template>
            <img
              v-if="m.has_media && isImage(m)"
              class="preview"
              :src="mediaUrl(m.id)"
              :alt="m.media_name || '图片'"
              @click="openMedia(m.id)"
            />
            <video
              v-else-if="m.has_media && isVideo(m)"
              class="preview"
              controls
              :src="mediaUrl(m.id)"
            />
            <div v-else-if="m.has_media && isPlayableAudio(m)" class="audio-wrap">
              <audio controls :src="mediaUrl(m.id)" />
            </div>
            <div v-else-if="m.has_media" class="file-row">
              <el-button size="small" type="primary" link @click="openMedia(m.id)">
                {{ m.msg_type === "voice" ? "下载语音" : "打开原文件" }}
              </el-button>
              <span class="t">{{ m.media_name }}</span>
            </div>
            <div v-else-if="isMediaType(m) && m.media_status === 'missing'" class="miss">
              本地没有已缓存的原文件
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api";
import { formatTime, formatDate, toIsoDate } from "../formatTime";

const filter = inject("filter");
const route = useRoute();
const items = ref([]);
const total = ref(0);
const page = ref(1);
const q = ref("");
const flag = ref("");
const selectedKey = ref(null);
const selectedMeta = ref(null);
const messages = ref([]);
const exporting = ref("");
const loadingChat = ref(false);
const chatBox = ref(null);
const drawerOpen = ref(false);

const selected = computed(() => {
  return items.value.find((row) => row.id === selectedKey.value) || selectedMeta.value;
});

function formatTableDate(value) {
  const iso = toIsoDate(value);
  return iso || "—";
}

function formatSegmentRange(start, end) {
  if (!start || !end) return "—";
  if (toIsoDate(start) === toIsoDate(end)) {
    const day = formatDate(start);
    const st = formatTime(start).split(" ").slice(1).join(" ");
    const et = formatTime(end).split(" ").slice(1).join(" ");
    return `${day} ${st} — ${et}`;
  }
  return `${formatTime(start)} — ${formatTime(end)}`;
}

function mediaUrl(id) {
  return `/api/messages/${id}/media`;
}

function isImage(m) {
  return (m.media_mime || "").startsWith("image/");
}

function isVideo(m) {
  return (m.media_mime || "").startsWith("video/");
}

function isPlayableAudio(m) {
  const mime = m.media_mime || "";
  return mime.startsWith("audio/") && mime !== "audio/silk";
}

function isMediaType(m) {
  return (
    ["image", "voice", "file", "video"].includes(m.msg_type)
    || isImage(m)
    || isVideo(m)
    || isPlayableAudio(m)
    || /^\[(图片|语音|文件|视频)\]/.test(m.content || "")
  );
}

function displayText(m) {
  if (linkCard(m)) return "";
  const raw = (m.content || "").trim();
  if (!raw) return "";
  const matched = raw.match(/^\[(图片|语音|文件|视频|链接)\]\s*([\s\S]*)$/);
  if (!matched) return raw;
  const rest = (matched[2] || "").trim();
  if (!rest || rest.startsWith("<")) return "";
  if (m.media_name && rest === m.media_name) return "";
  return rest;
}

function xmlTag(raw, name) {
  const m = raw.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, "i"));
  if (!m) return "";
  return stripTags(m[1].replace(/<!\[CDATA\[(.*?)\]\]>/gs, "$1"));
}

function stripTags(s) {
  return (s || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function safeHref(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
  } catch {
    /* ignore */
  }
  return "";
}

function isLinkMessage(m) {
  const raw = m.content || "";
  if (m.msg_type === "link") return true;
  if (raw.trim().startsWith("[链接]")) return true;
  if (/<appmsg[\s>]/i.test(raw) && /<url[\s>]/i.test(raw)) return true;
  return false;
}

function linkCard(m) {
  const raw = (m.content || "").trim();
  if (!isLinkMessage(m)) return null;
  let title = xmlTag(raw, "title");
  let desc = xmlTag(raw, "des");
  let url = xmlTag(raw, "url");
  const aHref = raw.match(/<a[^>]+href=["']?([^"'>\s]+)/i);
  if (!url && aHref) url = aHref[1];
  const body = raw.replace(/^\[链接\]\s*/, "");
  const lines = body.split(/\n/).map((s) => s.trim()).filter(Boolean);
  const httpRe = /https?:\/\/[^\s<>"']+/i;
  if (!url) {
    const hit = raw.match(httpRe);
    url = hit ? hit[0] : "";
  }
  if (!title) {
    const mixed = lines.find((s) => !httpRe.test(s)) || lines[0] || "";
    title = stripTags(mixed.replace(httpRe, " "));
  }
  if (!desc) {
    desc = stripTags(
      lines
        .map((s) => s.replace(httpRe, " "))
        .filter(Boolean)
        .join(" ")
    );
    if (desc === title) desc = "";
    else if (title && desc.startsWith(title)) desc = desc.slice(title.length).trim();
  }
  const href = safeHref(url);
  return {
    title: title || "链接",
    desc,
    url: href || url,
    href,
  };
}

function openMedia(id) {
  window.open(mediaUrl(id), "_blank");
}

async function load() {
  const data = await api.conversations({
    start_date: filter.value.start_date,
    end_date: filter.value.end_date,
    q: q.value,
    flag: flag.value,
    page: page.value,
    page_size: 20,
  });
  items.value = data.items;
  total.value = data.total;
}

async function scrollChat() {
  await nextTick();
  const box = chatBox.value;
  if (box) box.scrollTop = box.scrollHeight;
}

async function openDay(contactId, day, meta = null) {
  if (!contactId || !day) return;
  const key = `${contactId}:${day}`;
  selectedKey.value = key;
  selectedMeta.value = meta || items.value.find((row) => row.id === key) || selectedMeta.value;
  drawerOpen.value = true;
  loadingChat.value = true;
  try {
    messages.value = await api.dailyMessages({ contact_id: contactId, day });
  } finally {
    loadingChat.value = false;
  }
  await scrollChat();
}

async function openLegacyConversation(id) {
  if (!id) return;
  try {
    const meta = await api.conversation(id);
    await openDay(meta.contact_id, meta.day, meta);
  } catch {
    /* ignore */
  }
}

function onDrawerClosed() {
  selectedKey.value = null;
  selectedMeta.value = null;
  messages.value = [];
}

async function onRowClick(row) {
  if (!row?.contact_id || !row?.day) return;
  if (selectedKey.value === row.id && drawerOpen.value) return;
  await openDay(row.contact_id, row.day, row);
}

function reload() {
  page.value = 1;
  load();
}

async function exportFile(scope) {
  exporting.value = scope;
  try {
    const params =
      scope === "all"
        ? { scope: "all" }
        : {
            scope: "filtered",
            start_date: filter.value.start_date,
            end_date: filter.value.end_date,
            q: q.value,
            flag: flag.value,
          };
    const { blob, filename } = await api.exportXlsx(params);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || (scope === "all" ? "会话明细_全部.xlsx" : "会话明细_筛选.xlsx");
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    ElMessage.error(e.message);
  } finally {
    exporting.value = "";
  }
}

onMounted(async () => {
  if (route.query.flag) flag.value = String(route.query.flag);
  await load();
  if (route.query.contact_id && route.query.day) {
    await openDay(Number(route.query.contact_id), String(route.query.day));
  } else if (route.query.id) {
    await openLegacyConversation(Number(route.query.id));
  }
});

watch(
  filter,
  async () => {
    page.value = 1;
    await load();
  },
  { deep: true }
);

watch(
  () => route.query.id,
  (id) => {
    if (id) openLegacyConversation(Number(id));
  }
);

watch(
  () => [route.query.contact_id, route.query.day],
  ([contactId, day]) => {
    if (contactId && day) openDay(Number(contactId), String(day));
  }
);

watch(
  () => route.query.flag,
  (value) => {
    flag.value = value ? String(value) : "";
    reload();
  }
);
</script>

<style scoped>
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.list-pane {
  flex: 1;
  min-height: 0;
}
.pane {
  min-height: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.list-pane :deep(.el-table) { height: 100%; }
.conv-table :deep(.col-date .cell) { white-space: nowrap; }
.date-cell { white-space: nowrap; font-variant-numeric: tabular-nums; }
.warn-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.conv-table :deep(.col-warn .cell) { overflow: visible; }
.conv-table :deep(.el-table__row) { cursor: pointer; }
.table-wrap { flex: 1; min-height: 0; }
.pager { padding: 8px 12px; border-top: 1px solid var(--line); }
.chat-drawer :deep(.el-drawer__body) {
  padding: 0;
  height: 100%;
  overflow: hidden;
}
.drawer-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--panel);
}
.chat-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 52px 12px 16px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.chat-head-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
}
.chat-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
}
.empty { color: var(--muted); text-align: center; margin-top: 48px; }
.bubble {
  max-width: 86%;
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--panel2);
}
.bubble.customer { margin-right: auto; }
.bubble.cs {
  margin-left: auto;
  background: var(--accent-dim);
}
.bubble.system { margin: 0 auto 12px; background: transparent; color: var(--muted); }
.meta { margin-bottom: 4px; }
.t { color: var(--muted); margin-left: 8px; font-size: 12px; }
.sub { color: var(--muted); font-size: 12px; margin-top: 2px; line-height: 1.35; word-break: break-word; }
.sub.inline { display: inline; margin-top: 0; margin-left: 8px; }
.warn-head { cursor: help; border-bottom: 1px dashed var(--muted); }
.body { white-space: pre-wrap; word-break: break-word; }
.link-card {
  display: block;
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--bg2);
  color: inherit;
  text-decoration: none;
  max-width: 320px;
}
.link-card.clickable { cursor: pointer; }
.link-card.clickable:hover { border-color: var(--cyan); }
.link-kicker {
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--cyan);
  margin-bottom: 4px;
}
.link-title { font-weight: 600; line-height: 1.4; word-break: break-word; }
.link-desc { margin-top: 4px; font-size: 12px; color: var(--muted); word-break: break-word; }
.link-url {
  margin-top: 6px;
  font-size: 12px;
  color: var(--cyan);
  word-break: break-all;
}
.preview { display: block; max-width: 280px; max-height: 220px; margin-top: 8px; cursor: pointer; border-radius: 8px; }
.audio-wrap { margin-top: 8px; }
.file-row { margin-top: 6px; }
.miss { margin-top: 4px; color: var(--muted); font-size: 12px; }
@media (max-width: 980px) {
  .page { height: auto; }
  .list-pane { min-height: 360px; }
}
</style>
