const groups = document.getElementById("provider-groups");
const form = document.getElementById("provider-form");
const status = document.getElementById("status");
const configuredCount = document.getElementById("configured-count");
const freeModels = document.getElementById("free-models");
const runtimeStatus = document.getElementById("runtime-status");

let providers = [];
let localSettings = [];
let freeModelCatalog = [];
let runtime = null;
let settings = {
  cost_profile: "balanced",
  budget_usd: null,
  cost_profiles: [],
};

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
}

function setStatus(message, kind = "") {
  status.textContent = message;
  status.className = `status ${kind}`.trim();
}

function updateCount() {
  const total = providers.length;
  const configured = providers.filter((provider) => provider.configured).length;
  configuredCount.textContent = `${configured}/${total} mục đã cấu hình`;
}

function renderFreeModels() {
  if (!freeModelCatalog.length) {
    freeModels.innerHTML = '<div class="loading">Chưa đọc được danh mục model local.</div>';
    return;
  }
  freeModels.innerHTML = freeModelCatalog.map((model) => `
    <article class="free-model-card ${model.available ? "ready" : ""}">
      <div class="free-model-topline">
        <span class="free-model-category">${escapeHtml(model.category)}</span>
        <span class="free-model-state ${model.available ? "ready" : ""}"><i></i>${escapeHtml(model.status_label)}</span>
      </div>
      <h3>${escapeHtml(model.name)}</h3>
      <p>${escapeHtml(model.model)}</p>
      <small>${escapeHtml(model.requirements)}</small>
      <code>${escapeHtml(model.tool)} · ${escapeHtml(model.cost)}</code>
    </article>
  `).join("");
}

function runtimeCard(label, item) {
  const ready = Boolean(item?.available);
  return `<article class="runtime-card ${ready ? "ready" : "missing"}">
    <div class="runtime-card-topline"><strong>${escapeHtml(label)}</strong><span>${ready ? "SẴN SÀNG" : "CHƯA CÓ"}</span></div>
    <code>${escapeHtml(item?.version || item?.path || "Không phát hiện")}</code>
  </article>`;
}

function renderRuntime() {
  if (!runtime) {
    runtimeStatus.innerHTML = '<div class="loading">Chưa đọc được trạng thái runtime.</div>';
    return;
  }
  runtimeStatus.innerHTML = [
    runtimeCard("Node.js", runtime.node),
    runtimeCard("npm", runtime.npm),
    runtimeCard("npx / Remotion", { available: runtime.npx?.available && runtime.remotion?.available, version: runtime.npx?.version || runtime.remotion?.composer_dir }),
    runtimeCard("FFmpeg", runtime.ffmpeg),
    runtimeCard("ffprobe", runtime.ffprobe),
  ].join("");
}

function renderLocalSettings() {
  if (!localSettings.length) return "";
  return `
    <section class="local-settings-group">
      <div class="group-head"><h2>Cấu hình model local</h2></div>
      <div class="local-settings-list">
        ${localSettings.map((field) => {
          const value = field.value || "";
          if (field.type === "boolean") {
            return `<label class="local-setting-row checkbox-setting">
              <span><strong>${escapeHtml(field.label)}</strong><small>${escapeHtml(field.hint)}</small></span>
              <input type="checkbox" data-local-key="${escapeHtml(field.key)}" ${String(value).toLowerCase() === "true" ? "checked" : ""}>
            </label>`;
          }
          const control = field.type === "select"
            ? `<select data-local-key="${escapeHtml(field.key)}">${(field.options || []).map((option) => `<option value="${escapeHtml(option)}" ${value === option ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select>`
            : `<input type="${field.type === "url" ? "url" : "text"}" data-local-key="${escapeHtml(field.key)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(field.type === "url" ? "http://localhost:8188" : "Chưa cấu hình")}">`;
          return `<label class="local-setting-row"><span><strong>${escapeHtml(field.label)}</strong><small>${escapeHtml(field.hint)}</small></span>${control}</label>`;
        }).join("")}
      </div>
    </section>
  `;
}

function renderCostSettings() {
  const profileInput = document.getElementById("cost-profile");
  const budgetInput = document.getElementById("budget-usd");
  profileInput.innerHTML = (settings.cost_profiles || []).map((profile) => (
    `<option value="${escapeHtml(profile.key)}">${escapeHtml(profile.label)} — ${escapeHtml(profile.description)}</option>`
  )).join("");
  profileInput.value = settings.cost_profile || "balanced";
  budgetInput.value = settings.budget_usd == null ? "" : settings.budget_usd;
}

function render() {
  renderCostSettings();
  renderFreeModels();
  renderRuntime();
  const byGroup = new Map();
  for (const provider of providers) {
    if (!byGroup.has(provider.group)) byGroup.set(provider.group, []);
    byGroup.get(provider.group).push(provider);
  }
  groups.innerHTML = renderLocalSettings() + [...byGroup.entries()].map(([group, entries]) => `
    <section class="provider-group">
      <div class="group-head"><h2>${escapeHtml(group)}</h2></div>
      <div class="provider-list">
        ${entries.map((provider) => `
          <div class="provider-row" data-key="${escapeHtml(provider.key)}">
            <div class="provider-label">
              <strong>${escapeHtml(provider.label)}</strong>
              <span class="provider-state ${provider.configured ? "configured" : ""}">
                <i></i>${provider.configured ? "ĐÃ CẤU HÌNH" : "CHƯA CẤU HÌNH"}
              </span>
            </div>
            <div class="provider-key">${escapeHtml(provider.key)}</div>
            <div class="provider-hint">${escapeHtml(provider.hint)}</div>
            <div class="provider-input">
              <input type="password" name="${escapeHtml(provider.key)}" autocomplete="new-password" placeholder="${provider.masked ? `Đã lưu ${escapeHtml(provider.masked)}` : "Dán API key vào đây"}">
              <button type="button" data-action="toggle">HIỆN</button>
            </div>
            ${provider.configured ? `<label class="clear-row"><input type="checkbox" name="clear_${escapeHtml(provider.key)}"> Xóa khóa này khỏi máy</label>` : ""}
          </div>
        `).join("")}
      </div>
    </section>
  `).join("");
  updateCount();
}

async function load() {
  const response = await fetch("/api/settings/providers");
  if (!response.ok) throw new Error("Không tải được cấu hình provider");
  const payload = await response.json();
  providers = payload.providers || [];
  localSettings = payload.local_settings || [];
  settings = {
    cost_profile: payload.cost_profile || "balanced",
    budget_usd: payload.budget_usd ?? null,
    cost_profiles: payload.cost_profiles || [],
  };
  freeModelCatalog = await fetch("/api/free-models").then((response) => response.ok ? response.json() : []);
  runtime = await fetch("/api/runtime").then((response) => response.ok ? response.json() : null);
  render();
}

groups.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action=toggle]");
  if (!button) return;
  const input = button.parentElement.querySelector("input");
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  button.textContent = visible ? "HIỆN" : "ẨN";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const updates = {};
  const clear = [];
  for (const provider of providers) {
    const input = form.elements.namedItem(provider.key);
    const clearBox = form.elements.namedItem(`clear_${provider.key}`);
    if (input && input.value.trim()) updates[provider.key] = input.value.trim();
    if (clearBox && clearBox.checked) clear.push(provider.key);
  }
  for (const field of localSettings) {
    const input = form.querySelector(`[data-local-key="${CSS.escape(field.key)}"]`);
    if (!input) continue;
    const next = field.type === "boolean" ? (input.checked ? "true" : "false") : input.value.trim();
    const previous = field.value || "";
    if (next !== previous) updates[field.key] = next;
  }
  const profile = document.getElementById("cost-profile").value;
  const budgetInput = document.getElementById("budget-usd").value.trim();
  const budget = budgetInput === "" ? null : Number(budgetInput);
  const costChanged = profile !== settings.cost_profile || budget !== settings.budget_usd;
  if (!Object.keys(updates).length && !clear.length && !costChanged) {
    setStatus("Không có thay đổi để lưu.");
    return;
  }
  const saveButton = form.querySelector(".save-button");
  saveButton.disabled = true;
  setStatus("Đang lưu cấu hình…");
  try {
    const response = await fetch("/api/settings/providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates, clear, cost_profile: profile, budget_usd: budget }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Không lưu được cấu hình");
    providers = payload.providers || [];
    localSettings = payload.local_settings || localSettings;
    settings = {
      cost_profile: payload.cost_profile || "balanced",
      budget_usd: payload.budget_usd ?? null,
      cost_profiles: payload.cost_profiles || settings.cost_profiles,
    };
    freeModelCatalog = await fetch("/api/free-models").then((response) => response.ok ? response.json() : freeModelCatalog);
    runtime = await fetch("/api/runtime").then((response) => response.ok ? response.json() : runtime);
    render();
    setStatus("Đã lưu cấu hình an toàn vào .env local.", "success");
  } catch (error) {
    setStatus(error.message || "Không lưu được cấu hình", "error");
  } finally {
    saveButton.disabled = false;
  }
});

load().catch((error) => setStatus(error.message || "Không tải được cấu hình", "error"));
