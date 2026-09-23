// Shared helpers for the Backlot UI.

const VI = {
  "awaiting_human": "chờ bạn duyệt",
  "in_progress": "đang chạy",
  "completed": "đã xong",
  "pending": "chưa chạy",
  "failed": "thất bại",
  "research": "nghiên cứu",
  "proposal": "đề xuất",
  "idea": "ý tưởng",
  "script": "kịch bản",
  "scene_plan": "kế hoạch cảnh",
  "character_design": "thiết kế nhân vật",
  "rig_plan": "bộ khung nhân vật",
  "pose_library": "thư viện dáng",
  "assets": "tài nguyên",
  "edit": "dựng phim",
  "compose": "kết xuất",
  "publish": "xuất bản",
  "research_brief": "bản nghiên cứu",
  "proposal_packet": "gói đề xuất",
  "asset_manifest": "danh mục tài nguyên",
  "edit_decisions": "quyết định dựng",
  "render_report": "báo cáo kết xuất",
  "final_review": "kiểm tra cuối",
  "publish_log": "nhật ký xuất bản",
  "action_timeline": "timeline hành động",
  "character_design": "thiết kế nhân vật",
  "decision": "quyết định",
  "unknown": "chưa xác định",
  "animated-explainer": "video giải thích",
  "animation": "hoạt hình",
  "character-animation": "hoạt hình nhân vật",
  "cinematic": "điện ảnh",
  "documentary-montage": "phóng sự cắt dựng",
  "screen-demo": "demo màn hình",
  "talking-head": "người dẫn hình",
  "avatar-spokesperson": "avatar thuyết trình",
  "clip-factory": "xưởng video ngắn",
  "podcast-repurpose": "tái sử dụng podcast",
  "hybrid": "kết hợp",
  "localization-dub": "lồng tiếng bản địa hoá",
  "framework-smoke": "kiểm thử framework",
  "health-infographic": "video giải thích sức khỏe",
  "clean-professional": "chuyên nghiệp, sạch",
  "flat-motion-graphics": "motion graphics phẳng",
  "minimalist-diagram": "sơ đồ tối giản",
  "premium-minimalist": "tối giản cao cấp",
  "health-editorial": "infographic sức khỏe editorial",
  "health-editorial-pro": "editorial sức khỏe cao cấp",
  "health-clinical-3d": "sức khỏe clinical 3D",
  "health-food-documentary": "tài liệu thực phẩm",
  "templated": "theo mẫu",
  "atelier": "thủ công riêng",
  "remotion": "Remotion",
  "hyperframes": "HyperFrames",
  "ffmpeg": "FFmpeg",
};

export function tr(value, fallback = value) {
  return VI[String(value)] || fallback;
}

export function trStage(value) {
  return tr(value, String(value || "").replaceAll("_", " "));
}

export function trStatus(value) {
  return tr(value, String(value || "").replaceAll("_", " "));
}

export function trPipeline(value) {
  return tr(value, String(value || "").replaceAll("-", " "));
}

export function trArtifact(value) {
  return tr(value, String(value || "").replaceAll("_", " "));
}

export async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function fmtDuration(seconds) {
  const n = Number(seconds);
  if (seconds == null || !Number.isFinite(n)) return "";
  const s = Math.max(0, Math.round(n));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export function fmtMoney(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return "—";
  return `$${n.toFixed(2)}`;
}

export function fmtAgo(epochSeconds) {
  if (!epochSeconds) return "";
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 90) return "vừa xong";
  if (diff < 3600) return `${Math.round(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.round(diff / 3600)} giờ trước`;
  return `${Math.round(diff / 86400)} ngày trước`;
}

export function fmtClock(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

export function mediaURL(projectId, relPath) {
  return `/media/${encodeURIComponent(projectId)}/${relPath.split("/").map(encodeURIComponent).join("/")}`;
}

// Downscaled cached JPEG for images (full media only in players/lightbox).
export function thumbURL(projectId, relPath, w = 640) {
  return `/thumb/${encodeURIComponent(projectId)}/${relPath.split("/").map(encodeURIComponent).join("/")}?w=${w}`;
}

// Subscribe to a server-sent change feed; call onChange (debounced) per burst.
export function subscribe(url, onChange) {
  let timer = null;
  const source = new EventSource(url);
  source.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.type !== "change") return;
    } catch {
      return;
    }
    clearTimeout(timer);
    timer = setTimeout(onChange, 250);
  };
  source.onerror = () => { /* EventSource auto-reconnects */ };
  return source;
}

// Deterministic pseudo-waveform bars (seeded by a string).
export function waveBars(container, seedStr, count = 26, maxH = 14) {
  let seed = 0;
  for (const c of seedStr || "wave") seed = (seed * 31 + c.charCodeAt(0)) % 2147483647;
  seed = seed || 7;
  container.innerHTML = "";
  for (let i = 0; i < count; i++) {
    seed = (seed * 16807) % 2147483647;
    const h = 3 + ((seed % 100) / 100) * maxH * (0.55 + 0.45 * Math.sin(i / 5));
    const bar = document.createElement("i");
    bar.style.height = `${Math.max(3, h)}px`;
    container.append(bar);
  }
}

export const STAGE_ICONS = {
  completed: "✓",
  in_progress: "◉",
  awaiting_human: "◈",
  failed: "✕",
};
