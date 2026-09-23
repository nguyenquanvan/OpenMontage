// Backlot project board — renders BoardState and stays live via SSE.

import {
  STAGE_ICONS, el, fmtAgo, fmtClock, fmtDuration, fmtMoney,
  getJSON, mediaURL, subscribe, thumbURL, tr, trArtifact, trPipeline,
  trStage, trStatus, waveBars,
} from "/ui/lib.js";

const rawProjectPath = location.pathname.split("/p/")[1] || "";
const projectId = decodeURIComponent(rawProjectPath);
const encodedProjectId = encodeURIComponent(projectId);
const app = document.getElementById("app");
const modal = document.getElementById("modal");
const player = document.getElementById("player");

const THEME_KEY = "backlot.theme";
let currentTheme = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
let state = null;
let selectedStage = null;   // stage drawer open for this stage name
let activeRender = 0;
let replay = null;          // {t0, t1, t, playing} — replay mode when non-null
let firstPaint = true;
let run = { status: "idle" };
let appVersion = null;
let reviewAction = { stage: null, note: "", busy: false, message: "", error: false };
let assetMaterialization = null;
let assetMaterializationBusy = false;

function applyTheme(theme) {
  currentTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = currentTheme;
  localStorage.setItem(THEME_KEY, currentTheme);
}

function renderThemeToggle() {
  const next = currentTheme === "light" ? "dark" : "light";
  return el("button", {
    class: "theme-toggle",
    type: "button",
    title: `Chuyển sang giao diện ${next === "light" ? "sáng" : "tối"}`,
    "aria-label": `Chuyển sang giao diện ${next === "light" ? "sáng" : "tối"}`,
    "aria-pressed": currentTheme === "light" ? "true" : "false",
    onclick: () => {
      applyTheme(next);
      render();
    },
  }, el("span", { class: "theme-toggle-icon", "aria-hidden": "true" }, currentTheme === "light" ? "☾" : "☀"));
}

function renderMenuLinks() {
  return [
    el("a", { class: "settings-link menu-library", href: "/" }, "⌂ THƯ VIỆN"),
    el("a", { class: "settings-link menu-create", href: "/#new-project" }, "＋ TẠO DỰ ÁN"),
    el("a", { class: "settings-link menu-workflows", href: "/#workflows" }, "☰ LUỒNG LÀM VIỆC"),
    el("a", { class: "settings-link menu-settings", href: "/settings" }, "⚙ CÀI ĐẶT API"),
  ];
}

function renderMainMenu() {
  return el("nav", { class: "main-menu", "aria-label": "Menu chính" }, ...renderMenuLinks());
}

applyTheme(currentTheme);

// ---------------------------------------------------------------------------
// header slate
// ---------------------------------------------------------------------------

function renderSlate(s) {
  const board = s.storyboard;
  const chips = [
    el("span", { class: "chip" }, `Quy trình ${trPipeline(s.pipeline.pipeline_type)}`),
    board && board.total_duration_seconds
      ? el("span", { class: "chip" }, `${board.scenes.length} cảnh · ${fmtDuration(board.total_duration_seconds)}`)
      : null,
    s.style_playbook ? el("span", { class: "chip" }, s.style_playbook) : null,
    appVersion ? el("span", { class: "chip app-version", title: `Phiên bản ${appVersion.version} · build ${appVersion.build}` }, appVersion.label) : null,
  ];

  const awaiting = s.stages.find((x) => x.status === "awaiting_human");
  const inProgress = s.stages.find((x) => x.status === "in_progress");
  const stalled = s.stages.find((x) => x.stalled);
  let liveEl;
  if (awaiting) {
    liveEl = el("span", { class: "live" }, el("span", { class: "dot" }), "◈ CHỜ BẠN DUYỆT");
  } else if (stalled) {
    liveEl = el("span", { class: "live", style: "color:var(--red)" },
      el("span", { class: "dot", style: "background:var(--red);animation:none" }), "⚠ CÓ THỂ BỊ TREO");
  } else if (s.live || inProgress) {
    liveEl = el("span", { class: "live" }, el("span", { class: "dot" }), "ĐANG CHẠY");
  } else {
    liveEl = el("span", { class: "live idle" }, el("span", { class: "dot" }),
      `ĐANG CHỜ${s.last_activity ? " · " + fmtAgo(s.last_activity).toUpperCase() : ""}`);
  }

  const cost = el("div", { class: "cost" });
  const runBusy = run.status === "starting" || run.status === "running";
  const runAwaiting = run.status === "awaiting_human";
  if (s.cost) {
    const spent = s.cost.total_spent_usd ?? 0;
    const budget = spent + (s.cost.budget_remaining_usd ?? 0);
    const hasBudget = s.cost.budget_remaining_usd != null;
    const pct = hasBudget && budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;
    cost.append(el("div", { class: "nums" }, el("b", {}, fmtMoney(spent)),
      hasBudget ? el("span", {}, ` / ${fmtMoney(budget)}`) : ""));
    if (hasBudget) {
      cost.append(el("div", { class: "bar" }, el("i", {
        class: pct > 90 ? "crit" : pct > 75 ? "warn" : "", style: `width:${pct}%`,
      })));
    }
    cost.append(el("div", { class: "label" }, "chi phí tạo nội dung"));
  }

  return el("header", { class: "slate" },
    el("div", { class: "clapper" }),
    el("div", {},
      el("a", { class: "wordmark", href: "/", style: "text-decoration:none" }, "Backlot"),
      el("h1", {}, s.title),
    ),
    ...chips,
    el("div", { class: "spacer" }),
    el("button", {
      class: "settings-link primary-link run-button",
      type: "button",
      disabled: runBusy || runAwaiting ? true : null,
      onclick: openRunModal,
    }, runBusy ? "▶ ĐANG CHẠY" : runAwaiting ? "◈ CHỜ BẠN DUYỆT" : "▶ BẮT ĐẦU WORKFLOW"),
    renderMainMenu(),
    renderThemeToggle(),
    liveEl,
    cost,
  );
}

function goBackOrHome() {
  if (history.length > 1) {
    history.back();
    return;
  }
  location.assign("/");
}

function renderProjectRecovery(error) {
  const missing = String(error?.message || error).startsWith("404 ");
  document.title = `MOSA TOOL ALL — ${missing ? "Không tìm thấy dự án" : "Không mở được dự án"}`;
  document.body.classList.remove("first");
  app.innerHTML = "";
  app.append(
    el("header", { class: "slate recovery-slate" },
      el("div", { class: "clapper" }),
      el("div", { class: "recovery-brand" },
        el("a", { class: "wordmark", href: "/", style: "text-decoration:none" }, "Backlot"),
        el("h1", {}, "Điều hướng hệ thống"),
      ),
      appVersion ? el("span", {
        class: "chip app-version",
        title: `Phiên bản ${appVersion.version} · build ${appVersion.build}`,
      }, appVersion.label) : null,
      el("div", { class: "spacer" }),
      renderMainMenu(),
      renderThemeToggle(),
    ),
    el("main", { class: "recovery-page" },
      el("section", { class: "recovery-card", role: "alert" },
        el("span", { class: "recovery-kicker" }, missing ? "PROJECT NOT FOUND" : "PROJECT UNAVAILABLE"),
        el("h2", {}, missing ? "Không tìm thấy dự án" : "Không mở được dự án"),
        el("p", {}, missing
          ? `Dự án “${projectId || "không xác định"}” không tồn tại hoặc đã được di chuyển.`
          : "App chưa đọc được dữ liệu dự án. Bạn vẫn có thể quay lại các menu chính để tiếp tục."),
        el("div", { class: "recovery-actions" },
          el("button", { class: "recovery-button primary", type: "button", onclick: goBackOrHome }, "← QUAY LẠI"),
          el("a", { class: "recovery-button", href: "/" }, "THƯ VIỆN DỰ ÁN"),
          el("a", { class: "recovery-button", href: "/#new-project" }, "TẠO DỰ ÁN MỚI"),
        ),
        el("p", { class: "recovery-help" }, "Bạn cũng có thể dùng thanh menu phía trên để mở luồng làm việc hoặc cấu hình API."),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// stage rail
// ---------------------------------------------------------------------------

function stageSub(st) {
  if (st.status === "awaiting_human") return "chờ bạn duyệt\nduyệt trực tiếp bên dưới";
  if (st.status === "in_progress" && st.stalled) {
    return `có thể bị treo? không có hoạt động ${st.stalled_minutes} phút\nhỏi agent để biết trạng thái`;
  }
  if (st.status === "in_progress" && st.partial_progress) {
    const done = st.partial_progress.completed_scene_ids;
    if (Array.isArray(done)) return `${done.length} cảnh đã xong`;
    return "đang chạy";
  }
  if (st.status === "in_progress") return "đang chạy";
  if (st.status === "failed") return st.error ? String(st.error).slice(0, 60) : "thất bại";
  if (st.timestamp) {
    const approved = st.gated && st.human_approved ? " · đã duyệt" : "";
    return fmtClock(st.timestamp) + approved;
  }
  return "";
}

function renderRail(s) {
  const rail = el("nav", { class: "rail" });
  let pendingIndex = 1;
  for (const st of s.stages) {
    const cls = st.status === "completed" ? "done"
      : st.status === "in_progress" ? (st.stalled ? "active stalled" : "active")
      : st.status === "awaiting_human" ? "await"
      : st.status === "failed" ? "failed" : "";
    const icon = STAGE_ICONS[st.status] || String(pendingIndex);
    if (!STAGE_ICONS[st.status]) pendingIndex += 1;
    const node = el("div", {
      class: `stage ${cls}${selectedStage === st.name ? " selected" : ""}${st.undeclared ? " undeclared" : ""}`,
      title: st.undeclared ? `"${trStage(st.name)}" đã chạy nhưng không được khai báo trong manifest` : null,
      onclick: () => toggleDrawer(st.name),
    },
      el("span", { class: "line" }),
      el("span", { class: "node" }, icon),
      el("span", { class: "name" }, trStage(st.name)),
      el("span", { class: "sub", style: "white-space:pre-line" },
        st.undeclared ? `${stageSub(st)}\nchưa khai báo`.trim() : stageSub(st)),
    );
    rail.append(node);
  }
  return rail;
}

function toggleDrawer(stageName) {
  selectedStage = selectedStage === stageName ? null : stageName;
  render();
}

const STAGE_ARTIFACTS = {
  research: ["research_brief"],
  proposal: ["proposal_packet"],
  idea: ["brief"],
  script: ["script"],
  scene_plan: ["scene_plan"],
  assets: ["asset_manifest"],
  edit: ["edit_decisions"],
  compose: ["render_report", "final_review"],
  publish: ["publish_log"],
};

function artifactNamesForStage(st) {
  const declared = Array.isArray(st.produces) ? st.produces : [];
  const fallback = STAGE_ARTIFACTS[st.name] || [];
  return [...new Set([...declared, ...fallback].filter(Boolean))];
}

function reviewMetrics(review) {
  const nested = review && review.summary && typeof review.summary === "object"
    ? review.summary : {};
  return {
    critical: Number((review && review.critical) ?? nested.critical ?? 0),
    suggestions: Number((review && review.suggestions) ?? nested.suggestions ?? 0),
    nitpicks: Number((review && review.nitpicks) ?? nested.nitpicks ?? 0),
  };
}

function reviewSummaryText(review) {
  if (!review) return "";
  if (typeof review.summary === "string") return review.summary;
  const nested = review.summary && typeof review.summary === "object" ? review.summary : {};
  const counts = reviewMetrics(review);
  return [
    review.decision,
    `${counts.critical} lỗi nghiêm trọng`,
    `${counts.suggestions} đề xuất`,
    nested.review_focus_met ? `mục tiêu review ${nested.review_focus_met}` : null,
    nested.schema_validation,
  ].filter(Boolean).join(" · ");
}

function renderDrawer(s) {
  if (!selectedStage) return null;
  const st = s.stages.find((x) => x.name === selectedStage);
  if (!st) return null;

  const body = el("div", { class: "drawer-body" });

  if (st.review) {
    const metrics = reviewMetrics(st.review);
    const summary = reviewSummaryText(st.review);
    body.append(el("div", { class: "findings", style: "margin-bottom:12px" },
      el("span", { class: `f ${metrics.critical ? "crit" : ""}` }, `${metrics.critical} lỗi nghiêm trọng`),
      el("span", { class: `f ${metrics.suggestions ? "sugg" : ""}` }, `${metrics.suggestions} đề xuất`),
      el("span", { class: "f" }, `${metrics.nitpicks} lỗi nhỏ`),
      summary ? el("span", { style: "font-size:calc(11.5px * var(--fs-scale));color:var(--text-2);margin-left:8px" }, summary) : null,
    ));
  }

  const names = artifactNamesForStage(st);
  let shown = false;
  for (const name of names) {
    const artifact = s.artifacts[name];
    if (!artifact) continue;
    shown = true;
    body.append(
      el("div", { class: "d-cat", style: "font-family:var(--mono);font-size:calc(9.5px * var(--fs-scale));color:var(--text-3);letter-spacing:.1em;text-transform:uppercase;margin:6px 0 4px" }, trArtifact(name)),
      el("pre", {}, JSON.stringify(artifact, null, 2)),
    );
  }
  if (!shown) {
    body.append(el("div", { class: "hint" },
      st.status === "pending" ? "Stage này chưa chạy." : "Không tìm thấy artifact chuẩn trên ổ đĩa cho stage này."));
  }

  return el("div", { class: "drawer" },
    el("div", { class: "drawer-head" },
      el("h3", {}, `${trStage(st.name)} — ${trStatus(st.status)}`),
      st.gate_skipped ? el("span", { class: "gate-chip" }, "⚑ ĐÃ BỎ QUA CỔNG") : null,
      st.versions > 1 ? el("span", { class: "ver-chip" }, `v${st.versions}`) : null,
      st.timestamp ? el("span", { class: "meta", style: "font-family:var(--mono);font-size:calc(10.5px * var(--fs-scale));color:var(--text-3)" }, st.timestamp) : null,
      el("span", { class: "close", onclick: () => toggleDrawer(st.name) }, "ĐÓNG ✕"),
    ),
    body,
  );
}

// ---------------------------------------------------------------------------
// script card
// ---------------------------------------------------------------------------

function scriptSections(script, limit) {
  const sections = script.sections || [];
  const shown = limit ? sections.slice(0, limit) : sections;
  const nodes = [];
  for (const sec of shown) {
    nodes.push(el("div", { class: "sp-slug" },
      `${(sec.id || "").toUpperCase()} — ${sec.label || "Phần"} `,
      el("span", { class: "tc" }, `${fmtDuration(sec.start_seconds)} – ${fmtDuration(sec.end_seconds)}`)));
    if (sec.text) nodes.push(el("div", { class: "sp-action" }, sec.text));
    if (sec.speaker_directions) nodes.push(el("div", { class: "sp-paren" }, `(${sec.speaker_directions})`));
    const cues = sec.enhancement_cues || [];
    if (cues.length) {
      nodes.push(el("div", { style: "margin-left:42px" },
        cues.map((c) => el("span", { class: "sp-cue" }, `▸ ${c.type} · ${String(c.description || "").slice(0, 60)}`))));
    }
  }
  if (limit && sections.length > limit) {
    nodes.push(el("div", { class: "sp-fade" }, `… còn ${sections.length - limit} phần`));
  }
  return nodes;
}

function renderScriptCard(s) {
  const script = s.artifacts.script;
  if (!script) return null;
  const scriptStage = s.stages.find((x) => x.name === "script");
  const status = scriptStage ? scriptStage.status : "unknown";
  const stamp = status === "completed"
    ? el("span", { class: "script-status script-approved" }, "ĐÃ DUYỆT")
    : status === "awaiting_human"
      ? el("span", { class: "script-status script-pending" }, "CHỜ DUYỆT")
      : status === "in_progress"
        ? el("span", { class: "script-status script-draft" }, "ĐANG SOẠN")
        : null;

  const card = el("div", { class: "script-card script-preview", title: "Nhấn để mở toàn bộ kịch bản", onclick: openScriptModal },
    stamp,
    el("div", { class: "sp-title" }, script.title || s.title),
    el("div", { class: "sp-meta" },
      `kịch bản · ${fmtDuration(script.total_duration_seconds)} · ${(script.sections || []).length} phần`),
    ...scriptSections(script, 4),
    el("span", { class: "sp-expand" }, "⤢ MỞ TOÀN BỘ KỊCH BẢN"),
  );
  return card;
}

function humanize(value) {
  return trArtifact(value || "artifact");
}

function shortText(value, limit = 180) {
  const text = String(value || "").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function reviewFact(label, value) {
  if (value == null || value === "") return null;
  return el("div", { class: "approval-fact" },
    el("span", {}, label),
    el("b", {}, value),
  );
}

function reviewFacts(items) {
  const facts = items.filter(Boolean);
  return facts.length ? el("div", { class: "approval-facts" }, facts) : null;
}

function titledItems(items, selectedId = null) {
  const rows = (items || []).slice(0, 4).map((item, index) => {
    if (item == null) return null;
    if (typeof item !== "object") {
      return el("li", {}, shortText(item));
    }
    const id = item.id || item.concept_id || item.option_id;
    const title = item.title || item.name || item.display_name || item.label || id || item.path || item.platform || item.description || `Mục ${index + 1}`;
    const detail = item.hook || item.why_this_works || item.summary || item.description || item.silhouette_notes;
    return el("li", { class: id && id === selectedId ? "selected" : "" },
      el("div", { class: "approval-item-title" }, shortText(title, 100),
        id && id === selectedId ? el("span", { class: "approval-selected" }, "ĐÃ CHỌN") : null),
      detail && detail !== title ? el("p", {}, shortText(detail)) : null,
    );
  }).filter(Boolean);
  return rows.length ? el("ul", { class: "approval-items" }, rows) : null;
}

function genericArtifactSummary(artifact) {
  const facts = [];
  const items = [];
  for (const [key, value] of Object.entries(artifact || {})) {
    if (["version", "decision_log_ref"].includes(key)) continue;
    if (["string", "number", "boolean"].includes(typeof value)) {
      facts.push(reviewFact(humanize(key), shortText(value, 90)));
    } else if (Array.isArray(value)) {
      facts.push(reviewFact(humanize(key), `${value.length} mục`));
      if (!items.length && value.length) items.push(titledItems(value));
    }
    if (facts.length >= 6) break;
  }
  return [reviewFacts(facts), ...items].filter(Boolean);
}

function artifactReviewContent(name, artifact) {
  if (name === "brief") {
    return [
      artifact.hook ? el("p", { class: "approval-lead" }, artifact.hook) : null,
      reviewFacts([
        reviewFact("nền tảng", artifact.target_platform),
        reviewFact("thời lượng", artifact.target_duration_seconds != null ? fmtDuration(artifact.target_duration_seconds) : null),
        reviewFact("tông giọng", artifact.tone),
        reviewFact("phong cách", artifact.style),
      ]),
      titledItems(artifact.key_points),
    ].filter(Boolean);
  }
  if (name === "proposal_packet") {
    const selected = (artifact.selected_concept || {}).concept_id;
    const plan = artifact.production_plan || {};
    const cost = artifact.cost_estimate || {};
    return [
      reviewFacts([
        reviewFact("runtime", plan.render_runtime),
        reviewFact("pipeline", plan.pipeline),
        reviewFact("chi phí dự kiến", cost.total_estimated_usd != null ? fmtMoney(cost.total_estimated_usd) : null),
        reviewFact("số concept", Array.isArray(artifact.concept_options) ? artifact.concept_options.length : null),
      ]),
      titledItems(artifact.concept_options, selected),
      (artifact.selected_concept || {}).rationale
        ? el("p", { class: "approval-rationale" },
          el("b", {}, "VÌ SAO CHỌN CONCEPT NÀY  "), shortText(artifact.selected_concept.rationale))
        : null,
    ].filter(Boolean);
  }
  if (name === "research_brief") {
    return [
      artifact.topic ? el("p", { class: "approval-lead" }, artifact.topic) : null,
      reviewFacts([
        reviewFact("nguồn", Array.isArray(artifact.sources) ? artifact.sources.length : null),
        reviewFact("dữ liệu", Array.isArray(artifact.data_points) ? artifact.data_points.length : null),
        reviewFact("góc khai thác", Array.isArray(artifact.angles_discovered) ? artifact.angles_discovered.length : null),
      ]),
      titledItems(artifact.angles_discovered),
    ].filter(Boolean);
  }
  if (name === "script") {
    const first = (artifact.sections || [])[0];
    return [
      reviewFacts([
        reviewFact("thời lượng", fmtDuration(artifact.total_duration_seconds)),
        reviewFact("số phần", (artifact.sections || []).length),
      ]),
      first && first.text ? el("p", { class: "approval-lead" }, shortText(first.text, 220)) : null,
      el("p", { class: "approval-guidance" }, "Bản xem trước đầy đủ của kịch bản nằm ngay bên dưới."),
    ].filter(Boolean);
  }
  if (name === "scene_plan") {
    const scenes = artifact.scenes || [];
    const end = scenes.reduce((max, scene) => Math.max(max, Number(scene.end_seconds) || 0), 0);
    return [
      reviewFacts([
        reviewFact("số cảnh", scenes.length),
        reviewFact("thời lượng", end ? fmtDuration(end) : null),
      ]),
      titledItems(scenes),
      el("p", { class: "approval-guidance" }, "Kiểm tra thời lượng và độ phủ cảnh trong storyboard bên dưới."),
    ].filter(Boolean);
  }
  if (name === "asset_manifest") {
    const assets = artifact.assets || [];
    const types = [...new Set(assets.map((asset) => asset.type).filter(Boolean))];
    return [
      reviewFacts([
        reviewFact("tài nguyên", assets.length),
        reviewFact("loại", types.join(", ")),
        reviewFact("chi phí tạo", artifact.total_cost_usd != null ? fmtMoney(artifact.total_cost_usd) : null),
      ]),
      titledItems(assets),
      el("p", { class: "approval-guidance" }, "Kiểm tra từng bản quay trong dải hình trước khi duyệt bước kết xuất."),
    ].filter(Boolean);
  }
  if (name === "edit_decisions") {
    return [
      reviewFacts([
        reviewFact("đoạn dựng", Array.isArray(artifact.cuts) ? artifact.cuts.length : null),
        reviewFact("runtime", artifact.render_runtime || (artifact.metadata || {}).render_runtime),
      ]),
      titledItems(artifact.cuts),
    ].filter(Boolean);
  }
  if (name === "render_report") {
    return [
      reviewFacts([
        reviewFact("đầu ra", Array.isArray(artifact.outputs) ? artifact.outputs.length : null),
        reviewFact("thời lượng", artifact.duration_seconds != null ? fmtDuration(artifact.duration_seconds) : null),
      ]),
      titledItems(artifact.outputs),
    ].filter(Boolean);
  }
  if (name === "publish_log") {
    return [
      reviewFacts([reviewFact("nơi xuất bản", Array.isArray(artifact.entries) ? artifact.entries.length : null)]),
      titledItems((artifact.entries || []).map((entry) => ({
        title: entry.platform || entry.destination || "Nơi xuất bản",
        description: [entry.status, entry.url].filter(Boolean).join(" · "),
      }))),
    ].filter(Boolean);
  }
  return genericArtifactSummary(artifact);
}

function artifactReviewTitle(name, artifact, s) {
  if (name === "proposal_packet") {
    const selected = (artifact.selected_concept || {}).concept_id;
    const concept = (artifact.concept_options || []).find((item) => item.id === selected);
    return (concept && concept.title) || "Đề xuất sản xuất";
  }
  if (name === "research_brief") return artifact.topic || "Bản nghiên cứu";
  if (name === "scene_plan") return "Kế hoạch cảnh";
  if (name === "asset_manifest") return "Tài nguyên đã tạo";
  if (name === "edit_decisions") return "Quyết định dựng";
  if (name === "render_report") return "Báo cáo kết xuất";
  if (name === "publish_log") return "Kế hoạch xuất bản";
  return artifact.title || artifact.name || s.title;
}

async function submitApprovalReview(stage, action) {
  if (reviewAction.busy) return;
  const note = reviewAction.note.trim();
  if (action === "revise" && !note) {
    reviewAction = {
      ...reviewAction,
      message: "Hãy ghi rõ nội dung cần chỉnh sửa trước khi gửi.",
      error: true,
    };
    render();
    return;
  }

  reviewAction = {
    ...reviewAction,
    busy: true,
    message: action === "approve" ? "Đang lưu phê duyệt…" : "Đang gửi yêu cầu chỉnh sửa…",
    error: false,
  };
  render();
  try {
    const response = await fetch(`/api/project/${encodedProjectId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage, action, note }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không lưu được quyết định duyệt");
    reviewAction = {
      stage,
      note: "",
      busy: false,
      message: result.queued
        ? "Đã lưu. App sẽ tự tiếp tục khi agent hiện tại dừng."
        : result.resumed
          ? "Đã lưu. Workflow đang tiếp tục."
          : result.completed
            ? "Đã duyệt. Workflow đã hoàn tất."
            : result.error || "Đã lưu quyết định duyệt.",
      error: Boolean(result.error),
    };
    await refresh();
  } catch (error) {
    reviewAction = {
      ...reviewAction,
      busy: false,
      message: error.message || "Không lưu được quyết định duyệt",
      error: true,
    };
    render();
  }
}

async function startAssetMaterialization() {
  if (assetMaterializationBusy) return;
  assetMaterializationBusy = true;
  render();
  try {
    const response = await fetch(`/api/project/${encodedProjectId}/assets/materialization`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không bắt đầu tải được tài nguyên");
    assetMaterialization = result;
  } catch (error) {
    assetMaterialization = {
      ...(assetMaterialization || {}),
      ui_error: error.message || "Không bắt đầu tải được tài nguyên",
    };
  } finally {
    assetMaterializationBusy = false;
    render();
  }
}

function renderAssetMaterialization() {
  const info = assetMaterialization || {};
  const job = info.job || { status: "idle" };
  const active = ["queued", "downloading"].includes(job.status);
  const complete = Boolean(info.complete);
  const ready = Number(info.ready || 0);
  const total = Number(info.total || 0);
  const missing = Number(info.missing || 0);
  const pct = total ? Math.round((ready / total) * 100) : 0;
  const errors = Array.isArray(job.errors) ? job.errors : [];
  const statusText = complete
    ? `Đã kiểm tra đủ ${ready}/${total} file. Có thể duyệt và tiếp tục.`
    : active
      ? `Đang tải và kiểm tra ${ready}/${total} file${job.current ? ` · ${job.current}` : ""}.`
      : `Còn thiếu ${missing}/${total} file thật trên máy. Manifest hoặc đường dẫn web chưa phải tài nguyên dựng.`;
  return el("div", { class: `asset-materialization${complete ? " complete" : ""}` },
    el("div", { class: "asset-materialization-copy" },
      el("b", {}, complete ? "✓ TÀI NGUYÊN ĐÃ SẴN SÀNG" : "⬇ TẢI TÀI NGUYÊN 0 USD"),
      el("span", {}, statusText),
      info.ui_error ? el("em", {}, info.ui_error) : null,
      errors.length ? el("em", {}, `${errors.length} file chưa tải được: ${errors.slice(0, 2).map((item) => item.id).join(", ")}`) : null,
    ),
    el("div", { class: "asset-materialization-progress" },
      el("i", { style: `width:${pct}%` }),
    ),
    el("button", {
      type: "button",
      disabled: active || assetMaterializationBusy || complete ? true : null,
      onclick: startAssetMaterialization,
    }, complete ? "ĐÃ TẢI ĐỦ" : active || assetMaterializationBusy ? "ĐANG TẢI…" : "⬇ TẢI & KIỂM TRA FILE"),
  );
}

function renderApprovalReview(s) {
  const awaiting = s.stages.find((item) => item.status === "awaiting_human");
  if (!awaiting) return null;
  if (reviewAction.stage !== awaiting.name) {
    reviewAction = { stage: awaiting.name, note: "", busy: false, message: "", error: false };
  }

  const names = artifactNamesForStage(awaiting);
  const entries = names
    .filter((name) => name !== "decision_log")
    .map((name) => [name, s.artifacts[name]])
    .filter(([, artifact]) => artifact && typeof artifact === "object");
  const stageIndex = s.stages.findIndex((item) => item.name === awaiting.name);
  const nextStage = stageIndex >= 0 ? s.stages[stageIndex + 1] : null;
  const review = awaiting.review || {};
  const reviewSummary = reviewSummaryText(review);
  const assetsBlocked = awaiting.name === "assets" && assetMaterialization && !assetMaterialization.complete;

  const artifacts = entries.map(([name, artifact]) => el("article", {
    class: "approval-artifact",
    "data-artifact": name,
  },
    el("div", { class: "approval-artifact-kicker" }, humanize(name)),
    el("h2", {}, artifactReviewTitle(name, artifact, s)),
    ...artifactReviewContent(name, artifact),
  ));

  if (!artifacts.length) {
    artifacts.push(el("div", { class: "approval-missing", role: "alert" },
      el("b", {}, "Không có tài liệu nào để duyệt. "),
      names.length
        ? `Điểm kiểm ${trStage(awaiting.name)} khai báo ${names.map(humanize).join(", ")}, nhưng Backlot không tải được dữ liệu.`
        : `Điểm kiểm ${trStage(awaiting.name)} không khai báo tài liệu nào.`,
    ));
  }

  return el("section", { class: "approval-review", "data-stage": awaiting.name },
    el("div", { class: "approval-review-head" },
      el("div", {},
        el("div", { class: "approval-eyebrow" }, "CỔNG DUYỆT"),
        el("h2", {}, `${humanize(awaiting.name)} đã sẵn sàng để bạn duyệt`),
        el("p", {}, "Kiểm tra tài liệu, ghi chú nếu cần, rồi duyệt hoặc yêu cầu chỉnh sửa ngay tại đây."),
      ),
      el("span", { class: "approval-status" }, "CHỜ DUYỆT"),
    ),
    reviewSummary ? el("div", { class: "approval-review-note" },
      el("b", {}, "TỰ KIỂM TRA  "), shortText(reviewSummary, 260)) : null,
    awaiting.name === "assets" ? renderAssetMaterialization() : null,
    el("div", { class: "approval-artifacts" }, artifacts),
    el("div", { class: "approval-actions" },
      el("label", { class: "approval-feedback-label", for: `review-note-${awaiting.name}` },
        "GHI CHÚ DUYỆT / NỘI DUNG CẦN SỬA"),
      el("textarea", {
        id: `review-note-${awaiting.name}`,
        class: "approval-feedback",
        rows: "3",
        maxlength: "4000",
        placeholder: "Ví dụ: Đổi tiêu đề, rút ngắn phần mở đầu, dùng phương án 0 USD…",
        disabled: reviewAction.busy ? true : null,
        oninput: (event) => { reviewAction.note = event.target.value; },
      }, reviewAction.note),
      reviewAction.message ? el("div", {
        class: `approval-action-status${reviewAction.error ? " error" : ""}`,
        role: reviewAction.error ? "alert" : "status",
      }, reviewAction.message) : null,
      el("div", { class: "approval-action-buttons" },
        el("button", {
          class: "approval-revise",
          type: "button",
          disabled: reviewAction.busy ? true : null,
          onclick: () => submitApprovalReview(awaiting.name, "revise"),
        }, reviewAction.busy ? "ĐANG XỬ LÝ…" : "↺ YÊU CẦU CHỈNH SỬA"),
        el("button", {
          class: "approval-approve",
          type: "button",
          disabled: reviewAction.busy || assetsBlocked ? true : null,
          onclick: () => submitApprovalReview(awaiting.name, "approve"),
        }, reviewAction.busy ? "ĐANG XỬ LÝ…" : assetsBlocked ? "CHƯA ĐỦ FILE ĐỂ DUYỆT" : "✓ DUYỆT & TIẾP TỤC"),
      ),
    ),
    el("div", { class: "approval-review-foot" },
      el("span", {}, nextStage
        ? `Duyệt xong sẽ mở khóa ${humanize(nextStage.name)}.`
        : "Đây là cổng duyệt cuối cùng."),
      el("button", { type: "button", onclick: () => toggleDrawer(awaiting.name) }, "MỞ TÀI LIỆU ĐẦY ĐỦ"),
    ),
  );
}

function openScriptModal() {
  const script = state && state.artifacts.script;
  if (!script) return;
  modal.innerHTML = "";
  modal.append(
    el("span", { class: "modal-close", onclick: closeModal }, "ESC · ĐÓNG"),
    el("div", { class: "modal-page" },
      el("div", { class: "script-card", style: "cursor:default" },
        el("div", { class: "sp-title" }, script.title || state.title),
        el("div", { class: "sp-meta" },
          `kịch bản · ${fmtDuration(script.total_duration_seconds)} · ${(script.sections || []).length} phần`),
        ...scriptSections(script, 0),
        el("div", { class: "sp-fade" }, "HẾT"),
      )),
  );
  modal.classList.add("open");
}

function openNarrModal(card) {
  modal.innerHTML = "";
  const meta = [sceneLabel(card.id), card.section_label, fmtDuration(card.duration_seconds)]
    .filter(Boolean).join(" · ");
  modal.append(
    el("span", { class: "modal-close", onclick: closeModal }, "ESC · ĐÓNG"),
    el("div", { class: "modal-page" },
      el("div", { class: "script-card", style: "cursor:default" },
        el("div", { class: "sp-meta" }, meta),
        card.narration ? el("div", { class: "sp-action", style: "margin-left:0" }, card.narration) : null,
        card.shot_intent ? el("div", { class: "sp-paren", style: "margin-left:0" }, `Ý đồ — ${card.shot_intent}`) : null,
        card.description ? el("div", { class: "sp-paren", style: "margin-left:0" }, card.description) : null,
      )),
  );
  modal.classList.add("open");
}

function closeModal() { modal.classList.remove("open"); }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

async function openRunModal() {
  const currentBrief = state && state.brief ? state.brief : "";
  let agents = [];
  try {
    agents = await getJSON("/api/agents");
  } catch (error) {
    console.error(error);
  }
  const agentByName = new Map(agents.map((item) => [item.name, item]));
  const nextStage = (state?.stages || []).find((item) => item.status !== "completed")?.name || null;
  const pipelineType = state?.pipeline?.pipeline_type || null;
  const ollamaBlockReason = pipelineType === "health-infographic" && nextStage === "research"
    ? "Pipeline sức khỏe cần nguồn web và trích dẫn kiểm chứng. Dùng Codex/Claude cho nghiên cứu; dùng Ollama cho bước local sau."
    : pipelineType === "documentary-montage"
      ? "Pipeline phóng sự cần tìm và tải footage thật từ Pexels, Archive.org, NASA hoặc Wikimedia. Ollama chỉ có tool offline nên không thể hoàn thành luồng này."
      : null;
  const ollamaBlocked = Boolean(ollamaBlockReason);
  const ollama = agentByName.get("ollama") || {
    name: "ollama", label: "Ollama — miễn phí trên máy", available: false,
    online: false, models: [], recommended_model: "granite3.3:8b",
    setup_url: "https://ollama.com/download", detail: "Chưa đọc được trạng thái Ollama.",
  };
  modal.innerHTML = "";
  const status = el("p", { class: "run-status", role: "status" });
  const submit = el("button", { class: "create-project-button", type: "submit" }, "BẮT ĐẦU AGENT");
  const modelList = el("datalist", { id: "ollama-model-list" },
    ...(ollama.models || []).map((modelName) => el("option", { value: modelName })));
  const modelInput = el("input", {
    name: "model", type: "text", list: "ollama-model-list", placeholder: "Để agent tự chọn",
  });
  const agentSelect = el("select", { name: "agent" },
    el("option", { value: "auto" }, "Tự chọn (Codex → Claude)"),
    ...agents.filter((item) => item.name !== "ollama").map((item) => el(
      "option",
      { value: item.name },
      `${item.label}${item.available ? "" : " (chưa cài)"}`,
    )),
    el("option", { value: "ollama" },
      `Ollama Local · 0 USD${ollama.available ? "" : ollama.online ? " · thiếu model" : " · chưa chạy"}`),
  );
  const ollamaPanel = el("div", { class: "ollama-agent-panel", hidden: true });

  function renderOllamaPanel() {
    const selected = agentSelect.value === "ollama";
    ollamaPanel.hidden = !selected;
    submit.disabled = selected && ollamaBlocked;
    if (!selected) return;
    ollamaPanel.innerHTML = "";
    if (ollamaBlocked) {
      const useCodex = el("button", { type: "button", class: "ollama-download-button" }, "DÙNG CODEX — KHUYÊN DÙNG");
      useCodex.onclick = () => {
        agentSelect.value = agentByName.get("codex")?.available ? "codex" : "auto";
        status.textContent = "Đã chuyển sang agent có thể nghiên cứu và trích dẫn nguồn web.";
        status.className = "run-status success";
        renderOllamaPanel();
      };
      ollamaPanel.append(
        el("strong", {}, "OLLAMA KHÔNG PHÙ HỢP CHO LUỒNG NÀY"),
        el("span", {}, ollamaBlockReason),
        useCodex,
      );
      return;
    }
    if (ollama.online && (ollama.models || []).length) {
      ollamaPanel.append(
        el("strong", {}, "✓ OLLAMA LOCAL SẴN SÀNG"),
        el("span", {}, `${ollama.models.length} model trên máy · không cần API key · 0 USD/lượt.`),
      );
      modelInput.placeholder = `Tự chọn: ${ollama.models[0]}`;
      return;
    }
    if (ollama.online) {
      const download = el("button", { type: "button", class: "ollama-download-button" },
        `↓ TẢI ${String(ollama.recommended_model || "granite3.3:8b").toUpperCase()}`);
      download.onclick = async () => {
        download.disabled = true;
        download.textContent = "ĐANG BẮT ĐẦU TẢI…";
        status.textContent = "Ollama đang tải model. Có thể mất vài phút tùy tốc độ mạng.";
        status.className = "run-status";
        try {
          const response = await fetch("/api/agents/ollama/models", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: ollama.recommended_model || "granite3.3:8b" }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || "Không tải được model Ollama");
          download.textContent = "ĐANG TẢI MODEL…";
          const poll = window.setInterval(async () => {
            if (!modal.classList.contains("open")) {
              window.clearInterval(poll);
              return;
            }
            try {
              const latest = await getJSON("/api/agents");
              const next = latest.find((item) => item.name === "ollama");
              if (!next) return;
              Object.assign(ollama, next);
              if (next.installer?.status === "error") {
                window.clearInterval(poll);
                status.textContent = next.installer.detail || "Tải model thất bại.";
                status.className = "run-status error";
                renderOllamaPanel();
              } else if (next.available) {
                window.clearInterval(poll);
                status.textContent = "Đã tải model Ollama. Bạn có thể bắt đầu workflow.";
                status.className = "run-status success";
                modelList.replaceChildren(...next.models.map((name) => el("option", { value: name })));
                renderOllamaPanel();
              }
            } catch (error) {
              console.error(error);
            }
          }, 2500);
        } catch (error) {
          status.textContent = error.message || "Không tải được model Ollama";
          status.className = "run-status error";
          download.disabled = false;
          download.textContent = "THỬ TẢI LẠI";
        }
      };
      ollamaPanel.append(
        el("strong", {}, "OLLAMA ĐÃ CHẠY · CHƯA CÓ MODEL"),
        el("span", {}, "Tải model tool-calling miễn phí để agent đọc pipeline và ghi checkpoint."),
        download,
      );
      return;
    }
    ollamaPanel.append(
      el("strong", {}, "CẦN CÀI VÀ MỞ OLLAMA"),
      el("span", {}, "Ollama là runtime miễn phí chạy model ngay trên máy, không cần API key."),
      el("a", { href: ollama.setup_url || "https://ollama.com/download", target: "_blank", rel: "noreferrer" },
        "TẢI OLLAMA CHO WINDOWS / MAC ↗"),
    );
  }
  agentSelect.addEventListener("change", renderOllamaPanel);
  const form = el("form", {
    class: "run-form",
    onsubmit: async (event) => {
      event.preventDefault();
      const brief = form.querySelector("textarea").value.trim();
      const agent = agentSelect.value;
      const model = form.querySelector("input[name=model]").value.trim();
      const allowAutomation = form.querySelector("input[type=checkbox]").checked;
      if (!brief) {
        status.textContent = "Hãy mô tả video cần sản xuất.";
        status.className = "run-status error";
        return;
      }
      if (!allowAutomation) {
        status.textContent = "Bạn cần xác nhận cho phép agent chạy lệnh tự động.";
        status.className = "run-status error";
        return;
      }
      if (agent === "ollama" && ollamaBlocked) {
        status.textContent = ollamaBlockReason;
        status.className = "run-status error";
        return;
      }
      submit.disabled = true;
      status.textContent = "Đang khởi chạy agent…";
      status.className = "run-status";
      try {
        const response = await fetch(`/api/project/${encodedProjectId}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ brief, agent, model, allow_automation: allowAutomation }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Không khởi chạy được workflow");
        run = result;
        closeModal();
        await refresh();
      } catch (error) {
        status.textContent = String(error.message || "Không khởi chạy được workflow");
        status.className = "run-status error";
        submit.disabled = false;
      }
    },
  },
    el("div", { class: "run-form-kicker" }, "LOCAL AGENT RUNNER"),
    el("h2", {}, "Bắt đầu workflow"),
    el("p", {}, "Agent sẽ đọc pipeline, chạy các tool đã cấu hình và ghi checkpoint vào board này."),
    el("label", {},
      el("span", {}, "Brief sản xuất"),
      el("textarea", { name: "brief", rows: "6", placeholder: "Ví dụ: Tạo video 60 giây giới thiệu sản phẩm cho người mới…" }, currentBrief),
    ),
    el("div", { class: "run-form-grid" },
      el("label", {},
        el("span", {}, "Agent"),
        agentSelect,
      ),
      el("label", {},
        el("span", {}, "Model (tuỳ chọn)"),
        modelInput,
        modelList,
      ),
    ),
    ollamaPanel,
    el("label", { class: "run-confirm" },
      el("input", { type: "checkbox" }),
      el("span", {}, "Tôi cho phép agent chạy lệnh trong workspace dự án để tạo nội dung và render video."),
    ),
    status,
    submit,
  );
  modal.append(
    el("span", { class: "modal-close", onclick: closeModal }, "ESC · ĐÓNG"),
    el("div", { class: "modal-page" }, form),
  );
  modal.classList.add("open");
  renderOllamaPanel();
  form.querySelector("textarea").focus();
}

// ---------------------------------------------------------------------------
// right rail: decisions, activity
// ---------------------------------------------------------------------------

function renderDecisions(s) {
  const log = s.artifacts.decision_log;
  const decisions = (log && log.decisions) || [];
  if (!decisions.length) return null;
  const body = el("div", { class: "panel-body" });
  // Collapse by category+subject: a decision that changed mid-run (e.g. voice
  // openai_onyx → chirp3) is superseded by the later entry — show the CURRENT
  // choice, not the first one recorded, and mark that it was revised.
  const current = new Map();
  decisions.forEach((d, i) => {
    const key = `${d.category || "decision"}::${d.subject || ""}`;
    const prev = current.get(key);
    current.set(key, { d, order: i, revised: prev ? prev.revised + 1 : 0 });
  });
  const shown = [...current.values()].sort((a, b) => b.order - a.order).slice(0, 8);
  for (const { d, revised } of shown) {
    const selLabel = (() => {
      // Prefer the human label of the selected option over its bare id.
      const opt = (d.options_considered || []).find((o) => (o.option_id ?? o.label) === d.selected);
      return (opt && opt.label) || d.selected || "";
    })();
    const alts = (d.options_considered || [])
      .filter((o) => (o.option_id ?? o.label) !== d.selected && (o.option_id || o.label));
    body.append(el("div", { class: "decision" },
      el("div", { class: "d-cat" }, `${tr(d.category || "decision", d.category || "quyết định")}${d.confidence ? ` · ${d.confidence}` : ""}`,
        revised ? el("span", { class: "d-revised" }, " · đã sửa") : null),
      el("div", { class: "d-pick" }, `${d.subject || ""} `, el("span", { class: "arrow" }, "→"), ` ${selLabel}`),
      d.reason ? el("div", { class: "d-why" }, d.reason) : null,
      alts.length ? el("div", { class: "d-alt" }, "cũng đã cân nhắc: ",
        alts.slice(0, 3).map((o, i) => [i ? " · " : "", el("s", {}, o.label || o.option_id)]).flat()) : null,
    ));
  }
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "Quyết định"), el("span", { class: "meta" }, "decision_log.json")),
    body);
}

function renderActivity(s) {
  const events = s.events || [];
  if (!events.length) return null;
  const body = el("div", { class: "panel-body" });
  // A start is "running" only until a later finish/error for the same
  // tool+scene closes it — closed starts are dropped (the finish row tells
  // the story), unmatched starts render as live. Counted (not keyed-single)
  // so parallel runs of the same tool on the same scene stay visible.
  const open = new Map(); // key -> {count, ev}
  const rows = [];
  for (const ev of events) {
    const key = `${ev.tool}:${ev.scene_id || ""}`;
    if (ev.event === "start") {
      const slot = open.get(key) || { count: 0, ev };
      slot.count += 1;
      slot.ev = ev;
      open.set(key, slot);
    } else {
      const slot = open.get(key);
      if (slot) {
        slot.count -= 1;
        if (slot.count <= 0) open.delete(key);
      }
      rows.push(ev);
    }
  }
  for (const slot of open.values()) rows.push(slot.ev);
  rows.sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  for (const ev of rows.slice(-10).reverse()) {
    let statusEl;
    if (ev.event === "finish") {
      statusEl = el("span", { class: `status ${ev.success === false ? "err" : "ok"}` },
        `${ev.success === false ? "✕" : "✓"}${ev.duration_s != null ? ` ${ev.duration_s.toFixed ? ev.duration_s.toFixed(1) : ev.duration_s}s` : ""}${ev.cost_usd ? ` ${fmtMoney(ev.cost_usd)}` : ""}`);
    } else if (ev.event === "error") {
      statusEl = el("span", { class: "status err" }, "✕");
    } else {
      statusEl = el("span", { class: "status run" }, "● đang chạy");
    }
    body.append(el("div", { class: "act-row" },
      el("span", { class: "t" }, fmtClock(ev.ts)),
      el("span", { class: "tool" }, ev.tool || ""),
      el("span", { class: "target" }, ev.scene_id || ""),
      statusEl,
    ));
  }
  return el("div", { class: "panel" },
    el("div", { class: "panel-head" }, el("h2", {}, "Hoạt động"), el("span", { class: "meta" }, "events.jsonl")),
    body);
}

// ---------------------------------------------------------------------------
// storyboard filmstrip
// ---------------------------------------------------------------------------

function sceneLabel(id) {
  // "sc4" → "SC 04", "scene-11" → "SC 11", anything else → uppercased id
  const m = String(id).match(/(\d+)\s*$/);
  if (m) return `SC ${m[1].padStart(2, "0")}`;
  return String(id).toUpperCase().slice(0, 10);
}

function sceneCard(s, card) {
  const dur = card.duration_seconds;
  const width = Math.max(132, Math.min(300, 70 + (dur || 3) * 26));
  const wrap = el("div", { class: "scene-card", style: `width:${width}px` });

  const slate = el("div", { class: "sc-slate" },
    el("span", { class: "num" }, sceneLabel(card.id)),
    card.takes.length > 1 ? el("span", { class: "take" }, `T${card.takes.length}`) : null,
      card.hero_moment ? el("span", { class: "hero" }, "★ ĐIỂM NHẤN") : null,
    el("span", { class: "dur" }, fmtDuration(dur)),
  );
  wrap.append(slate);

  // visual slot
  let thumb;
  if (card.generating) {
    thumb = el("div", { class: "thumb generating" },
      el("div", { class: "shimmer" }),
      el("div", { class: "gen-label" },
        el("span", {}, "◉ ĐANG TẠO"),
        el("span", { class: "sub" }, card.generating_tool || "")));
  } else if (card.visual && card.visual.exists) {
    const v = card.visual;
    const badge = [v.model || v.source_tool, v.cost_usd != null ? fmtMoney(v.cost_usd) : null,
      v.quality_score != null ? `q ${v.quality_score}` : null].filter(Boolean).join(" · ");
    if (v.type === "video") {
      thumb = el("div", { class: "thumb approved" },
        el("video", { src: mediaURL(s.project_id, v.path), muted: "", preload: "metadata", playsinline: "" }),
        el("span", { class: "play" }, "▶"),
        badge ? el("span", { class: "badge" }, badge) : null);
      thumb.onclick = () => {
        const vid = thumb.querySelector("video");
        if (vid.paused) vid.play(); else vid.pause();
      };
    } else {
      const img = el("img", { src: thumbURL(s.project_id, v.path, 640), loading: "lazy", alt: "" });
      // A thumbnail that fails to load must never show a broken-image icon —
      // fall back to the shot spec in place (F: broken links).
      img.onerror = () => {
        const t = img.closest(".thumb");
        if (!t) return;
        t.className = "thumb spec";
        t.innerHTML = "";
        t.append(el("div", { class: "spec-in" },
          el("div", { class: "spec-desc" }, card.description || "không có tài nguyên"),
          el("div", { class: "spec-shot" }, [card.framing, card.movement].filter(Boolean).join(" · ").slice(0, 70))));
      };
      thumb = el("div", { class: "thumb approved" }, img,
        v.snapshot ? el("span", { class: "badge" }, "snapshot") : (badge ? el("span", { class: "badge" }, badge) : null));
    }
  } else if (card.type === "animation") {
    // Bespoke/atelier scene with no snapshot yet — name it as such rather
    // than "no asset yet" (the composition IS the asset).
    thumb = el("div", { class: "thumb spec bespoke" },
      el("div", { class: "spec-in" },
        el("span", { class: "bespoke-tag" }, "◆ THỦ CÔNG"),
        el("div", { class: "spec-desc" }, card.description || ""),
        el("div", { class: "spec-shot" }, "composition thủ công")));
  } else if (card.visual && !card.visual.exists) {
    thumb = el("div", { class: "thumb missing" },
      el("div", { class: "spec-in" },
        el("span", { class: "warn-ic" }, "⚑"),
        el("div", { class: "spec-desc" }, "có trong manifest nhưng thiếu file"),
        el("div", { class: "spec-shot" }, card.visual.path || "")));
  } else if (card.type === "text_card") {
    thumb = el("div", { class: "thumb textcard" },
      el("div", { class: "tc-copy" }, (card.narration || card.description || "").slice(0, 48)));
  } else if (card.required_assets.length) {
    const assetsStage = (s.stages || []).find((stage) => stage.name === "assets");
    const assetsFinished = assetsStage?.status === "completed";
    thumb = el("div", { class: assetsFinished ? "thumb missing" : "thumb spec planned" },
      el("div", { class: "spec-in" },
        el("span", { class: assetsFinished ? "warn-ic" : "planned-tag" }, assetsFinished ? "⚑" : "◇ SẼ TẠO LOCAL"),
        el("div", { class: "spec-desc" }, assetsFinished ? "thiếu tài nguyên sau bước tạo" : "tài nguyên dự kiến ở bước tiếp theo"),
        el("div", { class: "spec-shot" }, (card.required_assets[0].description || "").slice(0, 60))));
  } else {
    thumb = el("div", { class: "thumb spec" },
      el("div", { class: "spec-in" },
        el("div", { class: "spec-desc" }, card.description || ""),
        el("div", { class: "spec-shot" }, [card.framing, card.movement].filter(Boolean).join(" · ").slice(0, 70))));
  }
  wrap.append(thumb);

  // shot language chips
  const sl = card.shot_language;
  if (sl) {
    wrap.append(el("div", { class: "shotchips", style: "display:flex;flex-wrap:wrap;gap:4px;padding:7px 2px 0" },
      [sl.shot_size, sl.camera_movement, sl.lens_mm ? `${sl.lens_mm}mm` : null, sl.lighting_key]
        .filter(Boolean)
        .map((t) => el("span", { style: "font-family:var(--mono);font-size:calc(8.5px * var(--fs-scale));letter-spacing:.04em;color:#62626c;border:1px solid #212129;border-radius:3px;padding:1px 5px" }, String(t).replaceAll("_", " ")))));
  }

  // takes drawer
  if (card.takes.length > 1) {
    const takes = el("div", { class: "takes" });
    card.takes.forEach((t, i) => {
      const isActive = card.visual && (
        t === card.visual
        || (t.path && t.path === card.visual.path)
        || (t.id && t.id === card.visual.id)
      );
      const tk = el("span", { class: `tk${isActive ? " active" : ""}`, title: `take ${i + 1}` });
      if (t.exists && t.type === "image") tk.append(el("img", { src: thumbURL(s.project_id, t.path, 320), loading: "lazy", alt: "" }));
      takes.append(tk);
    });
    takes.append(el("span", { class: "tk-label" }, `${card.takes.length} BẢN QUAY`));
    wrap.append(takes);
  }

  // narration + audio — clickable to read in full (F: narration text cut off)
  if (card.narration) {
    const long = card.narration.length > 90;
    wrap.append(el("div", {
      class: `narr${long ? " clip" : ""}`,
      title: "Nhấn để đọc toàn bộ lời thoại",
      onclick: () => openNarrModal(card),
    }, card.narration, long ? el("span", { class: "narr-more" }, "⤢") : null));
  } else if (card.shot_intent || card.description) {
    wrap.append(el("div", { class: "narr tc-note" }, (card.shot_intent || card.description || "").slice(0, 110)));
  }
  const narrAudio = card.audio.find((a) => a.exists && (a.type === "narration" || a.type === "audio"));
  if (narrAudio) {
    const wave = el("div", { class: "wave", style: "cursor:pointer", title: "Phát lời thoại" });
    waveBars(wave, card.id + narrAudio.path);
    wave.append(el("span", { class: "wv-time" }, narrAudio.duration_seconds ? fmtDuration(narrAudio.duration_seconds) : "♪"));
    wave.onclick = () => {
      player.src = mediaURL(s.project_id, narrAudio.path);
      player.play();
    };
    wrap.append(wave);
  }
  return wrap;
}

function renderStoryboard(s) {
  const board = s.storyboard;
  if (!board) return null;
  const strip = el("div", { class: "filmstrip" });
  for (const card of board.scenes) strip.append(sceneCard(s, card));
  return el("div", {},
    el("div", { class: "section-title" }, "Storyboard",
      el("span", { class: "meta" },
        `${board.scenes.length} cảnh${board.total_duration_seconds ? ` · ${fmtDuration(board.total_duration_seconds)}` : ""} · độ rộng thẻ theo thời lượng`)),
    el("div", { class: "strip-outer" }, strip));
}

// ---------------------------------------------------------------------------
// renders + degraded media
// ---------------------------------------------------------------------------

function renderRenders(s) {
  const renders = s.media.renders;
  if (!renders.length) return null;
  if (activeRender >= renders.length) activeRender = 0;
  const current = renders[activeRender];
  // Full re-renders (every SSE refresh) must not reset an in-progress
  // watch: carry playback position/state over to the recreated element.
  const prev = document.querySelector(".render-hero video");
  const src = mediaURL(s.project_id, current.path);
  // preload="metadata" gives the element its intrinsic aspect ratio (and a
  // poster frame) before playback — without it a portrait 9:16 render sits
  // in a letterboxed 100%-wide black box that reads as landscape.
  const video = el("video", { src, controls: "", preload: "metadata" });
  // Click the frame to start playback (controls handle pause/scrub) — the
  // big player was inert to a click on the picture itself.
  video.addEventListener("click", () => { if (video.paused) video.play().catch(() => {}); });
  if (prev && prev.getAttribute("src") === src && (prev.currentTime > 0 || !prev.paused)) {
    const t = prev.currentTime;
    const wasPlaying = !prev.paused && !prev.ended;
    video.addEventListener("loadedmetadata", () => { video.currentTime = t; }, { once: true });
    video.setAttribute("preload", "metadata");
    if (wasPlaying) video.autoplay = true;
  }
  const versions = el("div", { class: "render-meta" },
    renders.map((r, i) => el("span", {
      class: `v${i === activeRender ? " active" : ""}`,
      onclick: () => { activeRender = i; render(); },
    }, `${r.path.split("/").pop()}${r.at_root ? " · root" : ""}`)),
    el("span", { style: "margin-left:auto" }, `${(current.size / 1048576).toFixed(1)} MB`),
  );
  return el("div", {},
    el("div", { class: "section-title" }, "Bản kết xuất",
      el("span", { class: "meta" }, `${renders.length} phiên bản`)),
    el("div", { class: "render-hero" }, video),
    versions);
}

function renderFoundMedia(s) {
  // Degraded view: show discovered snapshots when there's no storyboard.
  if (s.storyboard || !s.media.snapshots.length) return null;
  const grid = el("div", { class: "found-grid" });
  for (const snap of s.media.snapshots.slice(0, 12)) {
    grid.append(el("div", { class: "thumb" },
      el("img", { src: thumbURL(s.project_id, snap.path, 640), loading: "lazy", alt: "" })));
  }
  return el("div", {},
    el("div", { class: "section-title" }, "Dữ liệu watcher tìm thấy",
      el("span", { class: "meta" }, "ảnh snapshot / khung kiểm tra")),
    grid);
}

function renderNoState(s) {
  if (s.has_pipeline_state) return null;
  return el("div", { class: "notice", style: "border-color:#2b2b33;background:var(--surface-2);color:var(--text-3)" },
    el("span", { style: "font-size:calc(15px * var(--fs-scale))" }, "◌"),
    el("span", {},
      el("b", { style: "color:var(--text-2)" }, "Đã tạo workspace thành công. "),
      "Chưa có workflow nào được chạy, nên bảng chưa có checkpoint để hiển thị. ",
      "Khi agent bắt đầu production và ghi trạng thái, các bước, tài nguyên và tiến độ sẽ xuất hiện ở đây."));
}

function renderAwaitingNotice(s) {
  const awaiting = s.stages.find((x) => x.status === "awaiting_human");
  if (!awaiting) return null;
  return el("div", { class: "notice" },
    el("span", { style: "font-size:calc(16px * var(--fs-scale))" }, "◈"),
    el("span", {},
      el("b", {}, `Bước ${trStage(awaiting.name)} đang chờ bạn duyệt. `),
      "Agent đang tạm dừng tại cổng này — dùng các nút ", el("b", {}, "Duyệt & tiếp tục"),
      " hoặc ", el("b", {}, "Yêu cầu chỉnh sửa"), " ở bên dưới."));
}

// ---------------------------------------------------------------------------
// replay — scrub a completed run from its timestamps
// ---------------------------------------------------------------------------

// Python writers emit tz-aware UTC isoformat, but treat tz-naive strings as
// UTC too — mixing local-parsed and UTC-parsed timestamps would skew replay
// ordering by the user's UTC offset.
const ts = (iso) => {
  if (!iso) return null;
  let s = String(iso);
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += "Z";
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
};

function replayBounds(s) {
  const moments = [];
  for (const st of s.stages) {
    for (const h of st.history_entries || []) {
      const t = ts(h.timestamp);
      if (t) moments.push(t);
    }
  }
  for (const ev of s.events || []) {
    const t = ts(ev.ts);
    if (t) moments.push(t);
  }
  if (moments.length < 2) return null;
  return { t0: Math.min(...moments), t1: Math.max(...moments) };
}

function stateAt(s, T) {
  const view = structuredClone(s);
  for (const st of view.stages) {
    const past = (st.history_entries || []).filter((h) => ts(h.timestamp) != null && ts(h.timestamp) <= T);
    if (!past.length) {
      st.status = "pending"; st.review = null; st.timestamp = null;
      st.gate_skipped = false; st.partial_progress = null;
    } else {
      const cur = past[past.length - 1];
      st.status = cur.status || "pending";
      st.timestamp = cur.timestamp;
    }
  }
  view.events = (view.events || []).filter((ev) => ts(ev.ts) != null && ts(ev.ts) <= T);

  // Storyboard: visuals appear as their scene finishes (events) or when the
  // assets stage has completed as of T (legacy runs without events).
  if (view.storyboard) {
    const assetsStage = view.stages.find((x) => x.name === "assets");
    const assetsDone = assetsStage && assetsStage.status === "completed";
    const finished = new Set();
    const startedNow = new Map();
    for (const ev of view.events) {
      if (!ev.scene_id) continue;
      if (ev.event === "finish") { finished.add(ev.scene_id); startedNow.delete(ev.scene_id); }
      else if (ev.event === "start") startedNow.set(ev.scene_id, ev);
      else if (ev.event === "error") startedNow.delete(ev.scene_id);
    }
    const scenePlanStage = view.stages.find((x) => x.name === "scene_plan");
    const scenePlanDone = scenePlanStage && ["completed", "awaiting_human"].includes(scenePlanStage.status);
    if (!scenePlanDone) {
      view.storyboard = null;
    } else {
      for (const card of view.storyboard.scenes) {
        const visible = assetsDone || finished.has(card.id);
        if (!visible) { card.visual = null; card.takes = []; card.audio = []; }
        card.generating = startedNow.has(card.id);
        card.generating_tool = (startedNow.get(card.id) || {}).tool;
      }
    }
  }
  // Final artifacts hide until their stage happened — for every project
  // shape, storyboard or not (a degraded run must not show the finished
  // movie before its stages ran).
  const scriptStage = view.stages.find((x) => x.name === "script");
  if (!(scriptStage && ["completed", "awaiting_human"].includes(scriptStage.status))) {
    delete view.artifacts.script;
  }
  const composeStage = view.stages.find((x) => x.name === "compose");
  if (!(composeStage && composeStage.status === "completed")) {
    view.media.renders = [];
  }
  return view;
}

function renderReplayBar(s) {
  const bounds = replayBounds(s);
  if (!bounds) return null;
  if (!replay) {
    // collapsed: just the entry button
    return el("div", { class: "replay-bar", style: "justify-content:flex-end" },
      el("span", { class: "rp-time" }, "kéo để xem lại toàn bộ run"),
      el("span", { class: "rp-btn", onclick: startReplay }, "▶ XEM LẠI RUN"));
  }
  const pos = (replay.t - replay.t0) / Math.max(1, replay.t1 - replay.t0);
  const timeLabel = el("span", { class: "rp-time" },
    new Date(replay.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  const setT = (value) => {
    replay.t = replay.t0 + (Number(value) / 1000) * (replay.t1 - replay.t0);
    timeLabel.textContent = new Date(replay.t)
      .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };
  return el("div", { class: "replay-bar" },
    el("span", { class: "rp-btn", onclick: toggleReplayPlay }, replay.playing ? "❚❚" : "▶"),
    el("input", {
      type: "range", min: "0", max: "1000", value: String(Math.round(pos * 1000)),
      // A full render() would destroy this slider mid-drag: while dragging,
      // only pause + track the time label; re-render the board on release.
      onpointerdown: () => { replay.playing = false; },
      oninput: (e) => setT(e.target.value),
      onchange: (e) => { setT(e.target.value); render(); },
    }),
    timeLabel,
    el("span", { class: "rp-btn", onclick: stopReplay }, "✕ TRỰC TIẾP"),
  );
}

let replayTimer = null;

function startReplay() {
  const bounds = replayBounds(state);
  if (!bounds) return;
  replay = { ...bounds, t: bounds.t0, playing: true };
  document.body.classList.add("replaying");
  scheduleTick();
  render();
}

function stopReplay() {
  replay = null;
  clearTimeout(replayTimer);
  document.body.classList.remove("replaying");
  render();
}

function toggleReplayPlay() {
  if (!replay) return;
  replay.playing = !replay.playing;
  if (replay.playing) scheduleTick();
  render();
}

function scheduleTick() {
  // Single pending tick, ever — rapid pause/play must not stack chains.
  clearTimeout(replayTimer);
  replayTimer = setTimeout(tickReplay, 100);
}

function tickReplay() {
  if (!replay || !replay.playing) return;
  // A full run replays in ~20 seconds regardless of real duration
  // (10 renders/second — full re-render per tick, keep it modest).
  const step = (replay.t1 - replay.t0) / 200;
  replay.t = Math.min(replay.t1, replay.t + step);
  if (replay.t >= replay.t1) replay.playing = false;
  render();
  if (replay.playing) scheduleTick();
}

// ---------------------------------------------------------------------------
// page assembly
// ---------------------------------------------------------------------------

function render() {
  if (!state) return;
  const s = replay ? stateAt(state, replay.t) : state;
  document.title = `MOSA TOOL ALL — Backlot — ${s.title}`;
  document.body.classList.toggle("first", firstPaint);
  firstPaint = false;
  app.innerHTML = "";
  app.append(renderSlate(s));
  app.append(renderRail(s));
  const replayBar = renderReplayBar(state);
  if (replayBar) app.append(replayBar);
  const drawer = renderDrawer(s);
  if (drawer) app.append(drawer);
  const awaitingNotice = renderAwaitingNotice(s);
  if (awaitingNotice) app.append(awaitingNotice);
  const noState = renderNoState(s);
  if (noState) app.append(noState);

  const main = el("div", { class: "main-col" });
  const approvalReview = renderApprovalReview(s);
  if (approvalReview) main.append(approvalReview);
  const script = renderScriptCard(s);
  if (script) main.append(script);
  const aside = el("aside", {});
  const decisions = renderDecisions(s);
  const activity = renderActivity(s);
  if (decisions) aside.append(decisions);
  if (activity) aside.append(activity);

  // Media sections live INSIDE the main column so a tall decisions rail
  // never pushes them below the fold — the column flows beside the rail.
  const storyboard = renderStoryboard(s);
  const found = renderFoundMedia(s);
  const renders = renderRenders(s);

  if (approvalReview || script || decisions || activity) {
    for (const section of [storyboard, found, renders]) {
      if (section) main.append(section);
    }
    const hasAside = Boolean(decisions || activity);
    app.append(el("div", { class: `board${hasAside ? "" : " solo"}` }, main, hasAside ? aside : null));
  } else {
    for (const section of [storyboard, found, renders]) {
      if (section) app.append(section);
    }
  }
}

// Defensive normalization (F-02): the server contract guarantees these
// fields, but a sparse/legacy payload must degrade, never crash the board.
function normalize(s) {
  s.pipeline = s.pipeline || { pipeline_type: "unknown", stages: [], known: false };
  s.stages = Array.isArray(s.stages) ? s.stages : [];
  for (const stage of s.stages) {
    stage.produces = Array.isArray(stage.produces) ? stage.produces : [];
  }
  s.artifacts = s.artifacts || {};
  s.media = s.media || {};
  s.media.renders = Array.isArray(s.media.renders) ? s.media.renders : [];
  s.media.snapshots = Array.isArray(s.media.snapshots) ? s.media.snapshots : [];
  s.media.music = Array.isArray(s.media.music) ? s.media.music : [];
  s.events = Array.isArray(s.events) ? s.events : [];
  if (s.storyboard && Array.isArray(s.storyboard.scenes)) {
    for (const c of s.storyboard.scenes) {
      c.takes = Array.isArray(c.takes) ? c.takes : [];
      c.audio = Array.isArray(c.audio) ? c.audio : [];
      c.required_assets = Array.isArray(c.required_assets) ? c.required_assets : [];
    }
  } else {
    s.storyboard = null;
  }
  return s;
}

async function refresh() {
  const [nextState, nextRun, nextVersion, nextAssetMaterialization] = await Promise.all([
    getJSON(`/api/project/${encodeURIComponent(projectId)}/state`),
    getJSON(`/api/project/${encodeURIComponent(projectId)}/run`),
    getJSON("/api/version").catch(() => null),
    getJSON(`/api/project/${encodeURIComponent(projectId)}/assets/materialization`).catch(() => null),
  ]);
  state = normalize(nextState);
  run = nextRun;
  appVersion = nextVersion;
  assetMaterialization = nextAssetMaterialization;
  render();
}

async function boot() {
  try {
    await refresh();
  } catch (error) {
    appVersion = await getJSON("/api/version").catch(() => null);
    renderProjectRecovery(error);
    return;
  }

  // ?static=1 disables the live feed (screenshots, static exports).
  if (!new URLSearchParams(location.search).has("static")) {
    subscribe(`/api/project/${encodeURIComponent(projectId)}/events`, () => refresh().catch(console.error));
    window.setInterval(() => refresh().catch(console.error), 3000);
  }
}

boot();
