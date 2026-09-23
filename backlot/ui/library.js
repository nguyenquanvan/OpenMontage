import { el, fmtAgo, getJSON, subscribe, thumbURL, tr, trPipeline, trStage, trStatus } from "/ui/lib.js";

const grid = document.getElementById("grid");
const workflowList = document.getElementById("workflowList");
const workflowFilters = document.getElementById("workflowFilters");
const newProjectForm = document.getElementById("new-project-form");
const projectTitleInput = document.getElementById("project-title");
const projectIdInput = document.getElementById("project-id");
const projectPipelineInput = document.getElementById("project-pipeline");
const projectIntake = document.getElementById("project-intake");
const newProjectStatus = document.getElementById("new-project-status");
const THEME_KEY = "backlot.theme";
let currentTheme = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";

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
      const replacement = renderThemeToggle();
      document.querySelector(".theme-toggle").replaceWith(replacement);
    },
  }, el("span", { class: "theme-toggle-icon", "aria-hidden": "true" }, currentTheme === "light" ? "☾" : "☀"));
}

applyTheme(currentTheme);
document.getElementById("liveBadge").before(renderThemeToggle());

async function renderAppVersion() {
  const version = await getJSON("/api/version");
  const badge = document.getElementById("appVersion");
  if (!badge) return;
  badge.textContent = version.label;
  badge.title = `Phiên bản ${version.version} · build ${version.build}`;
}

const CATEGORY_LABELS = {
  generated: "AI tổng hợp",
  animation: "Hoạt hình",
  cinematic: "Điện ảnh",
  documentary: "Tài liệu",
  health: "Sức khỏe",
  custom: "Chuyên biệt",
  podcast: "Podcast",
};

const STABILITY_LABELS = {
  production: "ổn định",
  beta: "beta",
  experimental: "thử nghiệm",
};

let workflows = [];
let workflowFilter = "all";
let projectIdEdited = false;

function slugify(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/đ/g, "d")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function setNewProjectStatus(message, kind = "") {
  newProjectStatus.textContent = message;
  newProjectStatus.className = `new-project-status ${kind}`.trim();
}

function projectRequestError(error) {
  const message = String(error?.message || "");
  if (error instanceof TypeError || message.toLowerCase() === "failed to fetch") {
    return "Không kết nối được với máy chủ local. Hãy mở lại MOSA TOOL ALL rồi thử lại.";
  }
  return message || "Không tạo được dự án";
}

function workflowCard(workflow) {
  const stageNodes = workflow.stages.map((stage, index) => el("span", {
    class: `workflow-stage${stage.gated ? " gated" : ""}`,
    title: stage.gated ? "Cần bạn duyệt ở stage này" : "Tự động theo manifest",
  }, `${index + 1}. ${trStage(stage.name)}${stage.gated ? " ◈" : ""}`));
  const meta = [
    `${workflow.stages.length} stage`,
    workflow.budget_default_usd != null ? `từ ${trMoney(workflow.budget_default_usd)}` : null,
    workflow.max_wall_time_minutes ? `~${workflow.max_wall_time_minutes} phút` : null,
    workflow.reference_input ? "nhận video tham khảo" : null,
  ].filter(Boolean);
  return el("details", { class: "workflow-card" },
    el("summary", {},
      el("span", { class: "workflow-arrow" }, "›"),
      el("span", { class: "workflow-title" }, trPipeline(workflow.name)),
      el("span", { class: "workflow-category" }, CATEGORY_LABELS[workflow.category] || workflow.category),
      el("span", { class: `workflow-stability ${workflow.stability}` }, STABILITY_LABELS[workflow.stability] || workflow.stability),
    ),
    el("div", { class: "workflow-detail" },
      el("p", { class: "workflow-description" }, workflow.description),
      el("div", { class: "workflow-meta" }, ...meta.map((item) => el("span", {}, item))),
      el("div", { class: "workflow-stages" }, ...stageNodes),
      el("div", { class: "workflow-actions" },
        el("p", { class: "workflow-hint" }, "Chọn luồng này, điền brief và mở board để agent chạy theo checkpoint."),
        el("button", {
          class: "workflow-use-button",
          type: "button",
          onclick: () => selectWorkflow(workflow.name),
        }, "DÙNG LUỒNG NÀY"),
      ),
    ),
  );
}

function currentWorkflow() {
  return workflows.find((workflow) => workflow.name === projectPipelineInput.value) || null;
}

function intakeControl(field) {
  const common = {
    name: field.name,
    required: field.required ? "required" : null,
    placeholder: field.placeholder || null,
  };
  if (field.type === "select") {
    return el("select", common, ...(field.options || []).map((option) => el("option", {
      value: option.value,
      selected: String(option.value) === String(field.default ?? "") ? "selected" : null,
    }, option.label)));
  }
  if (field.type === "textarea") {
    return el("textarea", { ...common, rows: "3" }, field.default ?? "");
  }
  return el("input", {
    ...common,
    type: field.type === "number" ? "number" : field.type === "url" ? "url" : "text",
    value: field.default ?? "",
    min: field.min ?? null,
    max: field.max ?? null,
  });
}

function renderProjectIntake() {
  const workflow = currentWorkflow();
  const config = workflow?.project_intake;
  if (!config) {
    projectIntake.hidden = true;
    projectIntake.replaceChildren();
    newProjectForm.querySelector(".create-project-button").textContent = "KHỞI TẠO & MỞ BOARD";
    return;
  }
  const fields = (config.fields || []).map((field) => el("label", { class: field.type === "textarea" ? "wide" : "" },
    el("span", {}, field.label),
    intakeControl(field),
    field.help ? el("small", {}, field.help) : null,
  ));
  projectIntake.replaceChildren(
    el("div", { class: "project-intake-head" },
      el("strong", {}, config.title || trPipeline(workflow.name)),
      config.description ? el("p", {}, config.description) : null,
    ),
    el("div", { class: "project-intake-fields" }, ...fields),
  );
  projectIntake.hidden = false;
  newProjectForm.querySelector(".create-project-button").textContent = config.submit_label || "KHỞI TẠO & MỞ BOARD";
}

function selectWorkflow(name) {
  projectPipelineInput.value = name;
  renderProjectIntake();
  document.getElementById("new-project").scrollIntoView({ behavior: "smooth", block: "start" });
  projectTitleInput.focus({ preventScroll: true });
}

function trMoney(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : "—";
}

function renderWorkflowMenu() {
  const categories = ["all", ...new Set(workflows.map((workflow) => workflow.category))];
  workflowFilters.replaceChildren(...categories.map((category) => el("button", {
    class: `workflow-filter${workflowFilter === category ? " active" : ""}`,
    type: "button",
    onclick: () => {
      workflowFilter = category;
      renderWorkflowMenu();
    },
  }, category === "all" ? "TẤT CẢ" : CATEGORY_LABELS[category] || category)));
  const visible = workflowFilter === "all"
    ? workflows
    : workflows.filter((workflow) => workflow.category === workflowFilter);
  workflowList.replaceChildren(...visible.map(workflowCard));
}

async function renderWorkflows() {
  workflows = await getJSON("/api/workflows");
  projectPipelineInput.replaceChildren(
    el("option", { value: "" }, "Chọn luồng sản xuất…"),
    ...workflows.map((workflow) => el("option", { value: workflow.name }, trPipeline(workflow.name))),
  );
  renderProjectIntake();
  renderWorkflowMenu();
}

projectPipelineInput.addEventListener("change", renderProjectIntake);

projectTitleInput.addEventListener("input", () => {
  if (!projectIdEdited) projectIdInput.value = slugify(projectTitleInput.value);
});

projectIdInput.addEventListener("input", () => {
  projectIdEdited = true;
  projectIdInput.value = slugify(projectIdInput.value);
});

newProjectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = newProjectForm.querySelector(".create-project-button");
  const payload = {
    title: projectTitleInput.value.trim(),
    project_id: projectIdInput.value.trim(),
    pipeline_type: projectPipelineInput.value,
  };
  const workflow = currentWorkflow();
  if (workflow?.project_intake) {
    payload.intake = Object.fromEntries(
      [...projectIntake.querySelectorAll("input, textarea, select")].map((control) => [control.name, control.value.trim()]),
    );
  }
  if (!payload.title || !payload.project_id || !payload.pipeline_type) {
    setNewProjectStatus("Hãy điền tên, mã và chọn luồng sản xuất.", "error");
    return;
  }
  submit.disabled = true;
  setNewProjectStatus("Đang khởi tạo workspace…");
  try {
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không tạo được dự án");
    window.location.href = result.url;
  } catch (error) {
    setNewProjectStatus(projectRequestError(error), "error");
    submit.disabled = false;
  }
});

function miniRail(states) {
  const rail = el("div", { class: "mini-rail" });
  for (const s of states) {
    const cls = s.status === "completed" ? "d"
      : s.status === "in_progress" ? "a"
      : s.status === "awaiting_human" ? "w" : "";
    rail.append(el("i", { class: cls, title: `${trStage(s.name)}: ${trStatus(s.status)}` }));
  }
  return rail;
}

function card(p) {
  const poster = el("div", { class: "lib-poster" });
  if (p.poster) {
    poster.append(el("img", { src: thumbURL(p.project_id, p.poster, 640), loading: "lazy", alt: "" }));
  } else {
    poster.append(el("span", { class: "lp-txt" }, "CHƯA CÓ MEDIA"));
  }
  if (p.live && p.active_stage) {
    poster.append(el("span", { class: "lp-live" },
      el("span", { class: "dot" }),
      p.awaiting_human ? "◈ CHỜ BẠN DUYỆT" : `ĐANG CHẠY · ${trStage(p.active_stage).toUpperCase()}`));
  } else if (p.awaiting_human) {
    poster.append(el("span", { class: "lp-live" }, "◈ CHỜ BẠN DUYỆT"));
  }

  const meta = el("div", { class: "lb-meta" },
    el("span", { class: "chip" }, trPipeline(p.pipeline_type || "unknown")),
    p.scene_count ? el("span", { class: "chip" }, `${p.scene_count} cảnh`) : null,
    p.render_count ? el("span", { class: "chip" }, `${p.render_count} bản kết xuất`) : null,
    el("span", { class: "when" }, fmtAgo(p.last_activity)),
  );

  const staticSuffix = new URLSearchParams(location.search).has("static") ? "?static=1" : "";
  return el("a", { class: `lib-card${p.live ? " live-card" : ""}`, href: `/p/${p.project_id}${staticSuffix}`, style: "text-decoration:none;color:inherit" },
    poster,
    el("div", { class: "lib-body" },
      el("h3", {}, (p.title || p.project_id).toUpperCase()),
      meta,
      p.stage_states.length ? miniRail(p.stage_states) : null,
    ),
  );
}

async function render() {
  const projects = await getJSON("/api/projects");
  document.getElementById("count").textContent = `${projects.length} dự án`;
  const liveCount = projects.filter((p) => p.live && !p.awaiting_human).length;
  const awaitingCount = projects.filter((p) => p.awaiting_human).length;
  const badge = document.getElementById("liveBadge");
  badge.classList.toggle("idle", liveCount === 0 && awaitingCount === 0);
  badge.classList.toggle("awaiting", liveCount === 0 && awaitingCount > 0);
  document.getElementById("liveText").textContent = liveCount
    ? `${liveCount} ĐANG CHẠY`
    : awaitingCount
      ? `${awaitingCount} CHỜ DUYỆT`
      : "ĐANG CHỜ";
  grid.innerHTML = "";
  document.getElementById("empty").style.display = projects.length ? "none" : "block";
  for (const p of projects) grid.append(card(p));
}

render().catch(console.error);
renderAppVersion().catch((error) => console.error("Không đọc được phiên bản app", error));
renderWorkflows().catch((error) => {
  workflowList.replaceChildren(el("div", { class: "workflow-loading error" }, "Không tải được danh mục luồng làm việc."));
  console.error(error);
});
if (!new URLSearchParams(location.search).has("static")) {
  subscribe("/api/library/events", () => render().catch(console.error));
}
