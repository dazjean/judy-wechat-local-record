import { nextTick } from "vue";
import { toPng } from "html-to-image";

const FONT = '"PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif';

export function shareFilename(raw, fallback = "分享") {
  const safe = String(raw || "")
    .replace(/[\\/:*?"<>|]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
  const name = safe || fallback;
  return name.toLowerCase().endsWith(".png") ? name : `${name}.png`;
}

export async function sharePngBlob(blob, { filename, title } = {}) {
  if (!blob) throw new Error("没有可导出的内容");
  const name = shareFilename(filename, title || "分享");
  const file = new File([blob], name, { type: "image/png" });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: title || name });
      return "shared";
    } catch (err) {
      if (err && err.name === "AbortError") return "aborted";
    }
  }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
  return "downloaded";
}

function canvasToPngBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) reject(new Error("无法生成图片"));
      else resolve(blob);
    }, "image/png");
  });
}

const MAX_CANVAS = 8192;

function waitFrames(n = 2) {
  return new Promise((resolve) => {
    const step = () => {
      if (n <= 0) {
        resolve();
        return;
      }
      n -= 1;
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

const TABLE_EXPAND_SEL =
  ".el-table, .el-table__inner-wrapper, .el-table__header-wrapper, .el-table__body-wrapper, .el-table__header, .el-table__body, .el-scrollbar, .el-scrollbar__wrap, .el-scrollbar__view";

function unlockAncestors(el) {
  const saved = [];
  const remember = (node) => {
    saved.push({
      node,
      overflow: node.style.overflow,
      overflowX: node.style.overflowX,
      overflowY: node.style.overflowY,
      maxHeight: node.style.maxHeight,
      maxWidth: node.style.maxWidth,
      height: node.style.height,
    });
  };
  let node = el.parentElement;
  while (node && node !== document.documentElement) {
    const style = window.getComputedStyle(node);
    if (
      style.overflow !== "visible" ||
      style.overflowX !== "visible" ||
      style.overflowY !== "visible" ||
      style.maxHeight !== "none"
    ) {
      remember(node);
      node.style.overflow = "visible";
      node.style.overflowX = "visible";
      node.style.overflowY = "visible";
      node.style.maxHeight = "none";
    }
    node = node.parentElement;
  }
  el.querySelectorAll(TABLE_EXPAND_SEL).forEach((item) => {
    remember(item);
    item.style.overflow = "visible";
    item.style.overflowX = "visible";
    item.style.overflowY = "visible";
    item.style.maxHeight = "none";
    item.style.maxWidth = "none";
    item.style.height = "auto";
  });
  const main = el.closest(".el-main");
  const scrollTop = main ? main.scrollTop : 0;
  const scrollLeft = main ? main.scrollLeft : 0;
  if (main) {
    main.scrollTop = 0;
    main.scrollLeft = 0;
  }
  return () => {
    if (main) {
      main.scrollTop = scrollTop;
      main.scrollLeft = scrollLeft;
    }
    for (const item of saved) {
      item.node.style.overflow = item.overflow;
      item.node.style.overflowX = item.overflowX;
      item.node.style.overflowY = item.overflowY;
      item.node.style.maxHeight = item.maxHeight;
      item.node.style.maxWidth = item.maxWidth;
      item.node.style.height = item.height;
    }
  };
}

function expandClone(clone) {
  clone.style.margin = "0";
  clone.style.maxWidth = "none";
  clone.style.maxHeight = "none";
  clone.style.overflow = "visible";
  clone.style.overflowX = "visible";
  clone.style.overflowY = "visible";
  clone.style.boxSizing = "border-box";
  clone.querySelectorAll(TABLE_EXPAND_SEL).forEach((node) => {
    node.style.height = "auto";
    node.style.maxHeight = "none";
    node.style.maxWidth = "none";
    node.style.overflow = "visible";
    node.style.overflowX = "visible";
    node.style.overflowY = "visible";
  });
}

function measureCaptureBox(el) {
  const cs = window.getComputedStyle(el);
  const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
  const padY = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
  let width = Math.max(el.scrollWidth, el.offsetWidth, 1);
  let height = Math.max(el.scrollHeight, el.offsetHeight, 1);
  el.querySelectorAll("*").forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    width = Math.max(width, node.scrollWidth, node.offsetWidth);
    height = Math.max(height, node.scrollHeight);
  });
  // html-to-image 会把 width 写进克隆节点；border-box 下内边距会再吃掉一截，所以要加回去。
  return {
    width: Math.ceil(width + padX + 24),
    height: Math.ceil(height + padY + 24),
  };
}

async function captureFullPng(el, backgroundColor) {
  const restore = unlockAncestors(el);
  try {
    await waitFrames(2);
    const { width, height } = measureCaptureBox(el);
    const ratio = Math.min(2, MAX_CANVAS / width, MAX_CANVAS / height);
    const dataUrl = await toPng(el, {
      pixelRatio: ratio,
      backgroundColor,
      cacheBust: true,
      skipAutoScale: true,
      width,
      height,
      filter: (node) => !(node.classList && node.classList.contains("no-export")),
      style: {
        margin: "0",
        maxWidth: "none",
        maxHeight: "none",
        overflow: "visible",
        boxSizing: "border-box",
        transform: "none",
      },
      onclone: (doc, clone) => {
        const root = clone instanceof HTMLElement ? clone : doc.body?.firstElementChild;
        if (root instanceof HTMLElement) expandClone(root);
      },
    });
    return dataUrl;
  } finally {
    restore();
  }
}

export async function exportSharePng(el, { filename, title, backgroundColor = "#0e1116" } = {}) {
  if (!el) throw new Error("没有可导出的内容");
  el.classList.add("exporting");
  try {
    await nextTick();
    const dataUrl = await captureFullPng(el, backgroundColor);
    const res = await fetch(dataUrl);
    const blob = await res.blob();
    return sharePngBlob(blob, { filename, title });
  } finally {
    el.classList.remove("exporting");
  }
}

function wrapText(ctx, text, maxWidth) {
  const raw = (text || "").trim();
  if (!raw) return [];
  const chars = [...raw];
  const lines = [];
  let line = "";
  for (const ch of chars) {
    const next = line + ch;
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line);
      line = ch;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

function shortLabel(name) {
  const text = (name || "").trim();
  return text.length > 6 ? `${text.slice(0, 6)}…` : text;
}

export async function renderRelationMapPng({
  title = "活跃关系图谱",
  hint = "",
  nodes = [],
  edges = [],
  viewWidth = 920,
  viewHeight = 240,
  pixelRatio = 2,
} = {}) {
  const pad = 28;
  const graphW = viewWidth;
  const w = graphW + pad * 2;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  ctx.font = `12px ${FONT}`;
  const hintLines = wrapText(ctx, hint, w - pad * 2);
  const titleTrim = (title || "").trim();
  const showGroup = Boolean(titleTrim && titleTrim !== "活跃关系图谱");
  const headerH = 56;
  const groupH = showGroup ? 18 : 0;
  const hintH = hintLines.length ? hintLines.length * 18 + 8 : 0;
  const graphH = viewHeight + 8;
  const legendH = 32;
  const footerH = 36;
  const h = pad + headerH + groupH + hintH + graphH + legendH + footerH + 8;
  canvas.width = Math.round(w * pixelRatio);
  canvas.height = Math.round(h * pixelRatio);
  ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  ctx.fillStyle = "#1a2028";
  ctx.fillRect(0, 0, w, h);

  ctx.fillStyle = "#ffc94a";
  ctx.font = `600 11px ${FONT}`;
  ctx.fillText("RELATION MAP", pad, pad + 14);
  ctx.fillStyle = "#f2efe8";
  ctx.font = `800 20px ${FONT}`;
  ctx.fillText("活跃关系图谱", pad, pad + 40);
  let y = pad + headerH;
  if (showGroup) {
    ctx.fillStyle = "#9aa3af";
    ctx.font = `12px ${FONT}`;
    ctx.fillText(titleTrim, pad, pad + 58);
    y += groupH;
  }

  ctx.fillStyle = "#9aa3af";
  ctx.font = `12px ${FONT}`;
  for (const line of hintLines) {
    ctx.fillText(line, pad, y);
    y += 18;
  }
  y += hintLines.length ? 8 : 0;

  ctx.save();
  ctx.beginPath();
  ctx.rect(pad, y, graphW, viewHeight);
  ctx.clip();
  ctx.translate(pad, y);
  for (const edge of edges) {
    ctx.beginPath();
    ctx.moveTo(edge.x1, edge.y1);
    ctx.lineTo(edge.x2, edge.y2);
    ctx.strokeStyle = "rgba(56, 198, 255, 0.45)";
    ctx.lineWidth = edge.width || 1.5;
    ctx.lineCap = "round";
    ctx.stroke();
  }
  ctx.font = `11px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (const node of nodes) {
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.r || 8, 0, Math.PI * 2);
    ctx.fillStyle = node.fill || "#38c6ff";
    ctx.fill();
    ctx.fillStyle = "#f2efe8";
    ctx.fillText(shortLabel(node.name), node.x, node.y + (node.r || 8) + 4);
  }
  ctx.restore();
  y += graphH;

  const legend = [
    ["#ffc94a", "本机"],
    ["#ff6a3d", "建议加好友"],
    ["#3ddc97", "已是好友 / 已加"],
    ["#38c6ff", "再观察"],
    ["#6b7280", "暂不加"],
  ];
  ctx.font = `12px ${FONT}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  let lx = pad;
  for (const [color, label] of legend) {
    ctx.beginPath();
    ctx.arc(lx + 4, y + 10, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.fillStyle = "#9aa3af";
    ctx.fillText(label, lx + 14, y + 10);
    lx += ctx.measureText(label).width + 32;
  }
  y += legendH;

  ctx.strokeStyle = "#2a323e";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, y);
  ctx.lineTo(w - pad, y);
  ctx.stroke();
  ctx.fillStyle = "#9aa3af";
  ctx.font = `12px ${FONT}`;
  ctx.fillText("Judy · 活跃关系图谱", pad, y + 22);

  return canvasToPngBlob(canvas);
}
