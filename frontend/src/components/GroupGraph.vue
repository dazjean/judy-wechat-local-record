<template>
  <div ref="root" class="wrap">
    <div class="bar">
      <div>
        <div class="kicker">RELATION MAP</div>
        <div class="title">活跃关系图谱</div>
      </div>
      <div class="bar-right">
        <p class="hint no-export">{{ hint }}</p>
        <el-button
          class="no-export"
          :loading="exporting"
          :disabled="!canExport"
          @click="exportImage"
        >导出图片</el-button>
      </div>
    </div>
    <p class="share-only share-title">{{ shareTitle || "活跃关系图谱" }}</p>
    <p class="share-only share-hint">{{ shareHint }}</p>
    <svg
      ref="svg"
      class="canvas"
      :viewBox="`0 0 ${width} ${height}`"
      @pointermove="onMove"
      @pointerup="endDrag"
      @pointerleave="endDrag"
    >
      <line
        v-for="edge in layout.edges"
        :key="edge.source + '-' + edge.target"
        :x1="edge.x1"
        :y1="edge.y1"
        :x2="edge.x2"
        :y2="edge.y2"
        class="edge"
        :class="{ dim: selectedKey && !edge.hot }"
        :stroke-width="edge.width"
      />
      <g
        v-for="node in layout.nodes"
        :key="node.key"
        class="node"
        :class="{ on: selectedKey === node.key, dim: selectedKey && selectedKey !== node.key && !node.hot }"
        @pointerdown.prevent="startDrag($event, node.key)"
        @click="emit('select', node.key)"
      >
        <circle :cx="node.x" :cy="node.y" :r="node.r" :fill="node.fill" />
        <text :x="node.x" :y="node.y + node.r + 12">{{ shortName(node.name) }}</text>
      </g>
    </svg>
    <div class="legend">
      <span><i class="dot self"></i>本机</span>
      <span><i class="dot rec"></i>建议加好友</span>
      <span><i class="dot friend"></i>已是好友 / 已加</span>
      <span><i class="dot watch"></i>再观察</span>
      <span><i class="dot skip"></i>暂不加</span>
    </div>
    <footer class="share-footer">Judy · 活跃关系图谱</footer>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { renderRelationMapPng, sharePngBlob } from "../exportImage";

const props = defineProps({
  graph: { type: Object, default: () => ({ nodes: [], edges: [] }) },
  selectedKey: { type: String, default: "" },
  shareTitle: { type: String, default: "" },
});
const emit = defineEmits(["select"]);

const width = 920;
const height = 240;
const svg = ref(null);
const root = ref(null);
const exporting = ref(false);
const canExport = computed(() => (props.graph?.nodes || []).length > 0);
const sim = reactive({ nodes: [], dragging: "" });
let timer = null;
let pointerId = 0;

const hint = computed(() => {
  const g = props.graph || {};
  const edges = g.edge_count || 0;
  const iso = g.isolated || 0;
  const hub = g.hub?.name;
  if (!edges) return "线表示三分钟内紧挨着回复，或点了对方的名字。当前几乎没有互动。";
  const hubText = hub ? `互动最密是 ${hub}。` : "";
  return `线越粗互动越多。${hubText}${iso ? `有 ${iso} 人几乎不跟别人接话。` : ""}点节点可对照下方名册。`;
});
const shareHint = computed(() => hint.value.replace(/点节点可对照下方名册。?/, "").trim());

const neighbors = computed(() => {
  const map = {};
  for (const edge of props.graph?.edges || []) {
    (map[edge.source] ||= new Set()).add(edge.target);
    (map[edge.target] ||= new Set()).add(edge.source);
  }
  return map;
});

function fillFor(status, isSelf) {
  if (isSelf) return "#ffc94a";
  if (status === "recommend") return "#ff6a3d";
  if (status === "already_friend" || status === "added") return "#3ddc97";
  if (status === "skip") return "#6b7280";
  return "#38c6ff";
}

function shortName(name) {
  const text = (name || "").trim();
  return text.length > 6 ? `${text.slice(0, 6)}…` : text;
}

function seedNodes() {
  const raw = props.graph?.nodes || [];
  const n = Math.max(raw.length, 1);
  sim.nodes = raw.map((node, i) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const radius = Math.min(width, height) * 0.32;
    return {
      ...node,
      x: width / 2 + Math.cos(angle) * radius,
      y: height / 2 + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
      r: node.self ? 11 : Math.min(16, 6 + Math.sqrt(node.msg_count || 1) * 1.6),
      fill: fillFor(node.status, node.self),
      pinned: false,
    };
  });
}

function tick() {
  const nodes = sim.nodes;
  if (nodes.length < 2) return;
  const k = 1400;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      let dx = nodes[j].x - nodes[i].x;
      let dy = nodes[j].y - nodes[i].y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = k / (dist * dist);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      if (!nodes[i].pinned) {
        nodes[i].vx -= fx;
        nodes[i].vy -= fy;
      }
      if (!nodes[j].pinned) {
        nodes[j].vx += fx;
        nodes[j].vy += fy;
      }
    }
  }
  const byKey = Object.fromEntries(nodes.map((n) => [n.key, n]));
  for (const edge of props.graph?.edges || []) {
    const a = byKey[edge.source];
    const b = byKey[edge.target];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const rest = 92;
    const pull = (dist - rest) * 0.012 * (1 + Math.min(edge.weight || 1, 8) * 0.08);
    const fx = (dx / dist) * pull;
    const fy = (dy / dist) * pull;
    if (!a.pinned) {
      a.vx += fx;
      a.vy += fy;
    }
    if (!b.pinned) {
      b.vx -= fx;
      b.vy -= fy;
    }
  }
  for (const node of nodes) {
    if (node.pinned) {
      node.vx = 0;
      node.vy = 0;
      continue;
    }
    node.vx += (width / 2 - node.x) * 0.01;
    node.vy += (height / 2 - node.y) * 0.01;
    node.vx *= 0.82;
    node.vy *= 0.82;
    node.x = Math.min(width - 36, Math.max(36, node.x + node.vx));
    node.y = Math.min(height - 28, Math.max(24, node.y + node.vy));
  }
}

const layout = computed(() => {
  const byKey = Object.fromEntries(sim.nodes.map((n) => [n.key, n]));
  const hot = neighbors.value[props.selectedKey] || new Set();
  const edges = (props.graph?.edges || []).map((edge) => {
    const a = byKey[edge.source];
    const b = byKey[edge.target];
    if (!a || !b) return null;
    return {
      ...edge,
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      width: Math.min(5, 1 + Math.log2((edge.weight || 1) + 1)),
      hot: !props.selectedKey || edge.source === props.selectedKey || edge.target === props.selectedKey,
    };
  }).filter(Boolean);
  return {
    nodes: sim.nodes.map((n) => ({ ...n, hot: hot.has(n.key) })),
    edges,
  };
});

function startLoop() {
  stopLoop();
  let n = 0;
  timer = window.setInterval(() => {
    tick();
    n += 1;
    if (n > 90 && !sim.dragging) stopLoop();
  }, 24);
}

function stopLoop() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

function startDrag(ev, key) {
  const node = sim.nodes.find((n) => n.key === key);
  if (!node) return;
  sim.dragging = key;
  node.pinned = true;
  pointerId = ev.pointerId;
  svg.value?.setPointerCapture?.(ev.pointerId);
  startLoop();
}

function onMove(ev) {
  if (!sim.dragging || ev.pointerId !== pointerId || !svg.value) return;
  const pt = toLocal(ev);
  const node = sim.nodes.find((n) => n.key === sim.dragging);
  if (!node) return;
  node.x = pt.x;
  node.y = pt.y;
}

function endDrag() {
  const node = sim.nodes.find((n) => n.key === sim.dragging);
  if (node) node.pinned = false;
  sim.dragging = "";
}

function toLocal(ev) {
  const rect = svg.value.getBoundingClientRect();
  return {
    x: ((ev.clientX - rect.left) / rect.width) * width,
    y: ((ev.clientY - rect.top) / rect.height) * height,
  };
}

watch(
  () => props.graph,
  () => {
    seedNodes();
    startLoop();
  },
  { deep: true }
);

onMounted(() => {
  seedNodes();
  startLoop();
});
onUnmounted(stopLoop);

async function exportImage() {
  if (exporting.value || !canExport.value) return;
  exporting.value = true;
  try {
    const title = props.shareTitle || "活跃关系图谱";
    const blob = await renderRelationMapPng({
      title,
      hint: shareHint.value,
      nodes: layout.value.nodes,
      edges: layout.value.edges,
      viewWidth: width,
      viewHeight: height,
    });
    const result = await sharePngBlob(blob, { filename: title, title });
    if (result === "shared") ElMessage.success("已打开分享");
    else if (result === "downloaded") ElMessage.success("已导出图片，可直接转发分享");
  } catch {
    ElMessage.error("导出失败，请稍后重试");
  } finally {
    exporting.value = false;
  }
}
</script>

<style scoped>
.wrap {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 12px 8px;
  flex-shrink: 0;
}
.bar { display: flex; justify-content: space-between; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.bar-right { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; }
.kicker { font-size: 11px; letter-spacing: 0.18em; color: var(--warn); font-weight: 600; }
.title { font-weight: 800; }
.hint { margin: 0; color: var(--muted); font-size: 12px; max-width: 560px; line-height: 1.5; }
.share-only { display: none; }
.wrap.exporting .share-only { display: block; }
.wrap.exporting .no-export { display: none !important; }
.wrap.exporting .node.dim { opacity: 1; }
.wrap.exporting .edge.dim { stroke: rgba(56, 198, 255, 0.35); }
.wrap.exporting .node.on circle { stroke: none; }
.share-title { margin: 8px 0 4px; font-weight: 700; }
.share-hint { margin: 0 0 8px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.share-footer { display: none; }
.wrap.exporting .share-footer {
  display: block;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  letter-spacing: 0.12em;
}
.canvas { width: 100%; height: 220px; display: block; touch-action: none; }
.edge { stroke: rgba(56, 198, 255, 0.35); }
.edge.dim { stroke: rgba(42, 50, 62, 0.7); }
.node { cursor: pointer; }
.node text {
  fill: #f2efe8;
  font-size: 11px;
  text-anchor: middle;
  pointer-events: none;
}
.node.on circle { stroke: #fff; stroke-width: 2; }
.node.dim { opacity: 0.28; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 12px; padding: 4px 4px 2px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.dot.self { background: var(--warn); }
.dot.rec { background: var(--accent); }
.dot.friend { background: var(--good); }
.dot.watch { background: var(--cyan); }
.dot.skip { background: #6b7280; }
</style>
