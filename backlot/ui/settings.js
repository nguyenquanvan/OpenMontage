const groups = document.getElementById("provider-groups");
const form = document.getElementById("provider-form");
const status = document.getElementById("status");
const configuredCount = document.getElementById("configured-count");
const freeModels = document.getElementById("free-models");
const runtimeStatus = document.getElementById("runtime-status");
const appVersion = document.getElementById("app-version");
const appBuild = document.getElementById("app-build");
const checkUpdateButton = document.getElementById("check-update");
const installUpdateButton = document.getElementById("install-update");
const updateStatus = document.getElementById("update-status");

let providers = [];
let localSettings = [];
let freeModelCatalog = [];
let runtime = null;
let modelPollTimer = null;
let updatePollTimer = null;
let selectedModelTier = "all";
let settings = {
  cost_profile: "balanced",
  budget_usd: null,
  cost_profiles: [],
};

async function loadAppVersion() {
  const version = await fetch("/api/version").then((response) => {
    if (!response.ok) throw new Error("Không đọc được phiên bản app");
    return response.json();
  });
  appVersion.textContent = version.label;
  appBuild.textContent = `MOSA_APP_VERSION=${version.version} · MOSA_APP_BUILD=${version.build}`;
}

function renderUpdate(payload) {
  const job = payload.job || {};
  const busy = ["queued", "downloading", "verifying", "launching"].includes(job.status);
  checkUpdateButton.disabled = busy;
  installUpdateButton.disabled = busy;
  installUpdateButton.hidden = !payload.update_available || !payload.install_supported;
  if (busy) {
    updateStatus.textContent = `${job.detail || "Đang cập nhật…"} ${job.progress || 0}%`;
  } else if (job.status === "launched") {
    updateStatus.textContent = job.detail;
  } else if (job.status === "error") {
    updateStatus.textContent = `Lỗi cập nhật: ${job.detail}`;
  } else if (payload.error) {
    updateStatus.textContent = `Không kiểm tra được GitHub: ${payload.error}`;
  } else if (payload.update_available) {
    updateStatus.textContent = `Có bản v${payload.latest_version}: ${payload.asset_name || "mở trang phát hành"}.`;
  } else {
    updateStatus.textContent = `Đang dùng bản mới nhất v${payload.current_version}.`;
  }
  if (busy && !updatePollTimer) {
    updatePollTimer = window.setInterval(() => checkForUpdate(false).catch(console.error), 1200);
  } else if (!busy && updatePollTimer) {
    window.clearInterval(updatePollTimer);
    updatePollTimer = null;
  }
}

async function checkForUpdate(force = false) {
  const response = await fetch(`/api/app-update?force=${force ? "true" : "false"}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Không kiểm tra được cập nhật");
  renderUpdate(payload);
  return payload;
}

checkUpdateButton.addEventListener("click", async () => {
  checkUpdateButton.disabled = true;
  updateStatus.textContent = "Đang kiểm tra GitHub Releases…";
  try {
    await checkForUpdate(true);
  } catch (error) {
    updateStatus.textContent = error.message || "Không kiểm tra được cập nhật";
  } finally {
    checkUpdateButton.disabled = false;
  }
});

installUpdateButton.addEventListener("click", async () => {
  if (!window.confirm("Tải bản mới, kiểm tra SHA-256 và mở trình cài đặt? App có thể tự đóng trong lúc cập nhật.")) return;
  installUpdateButton.disabled = true;
  updateStatus.textContent = "Đang chuẩn bị bản cập nhật…";
  try {
    const response = await fetch("/api/app-update/install", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Không bắt đầu được cập nhật");
    renderUpdate(payload);
  } catch (error) {
    updateStatus.textContent = error.message || "Không bắt đầu được cập nhật";
    installUpdateButton.disabled = false;
  }
});

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
  const visibleModels = freeModelCatalog.filter((model) => selectedModelTier === "all" || model.installer?.tier === selectedModelTier);
  freeModels.innerHTML = visibleModels.map((model) => {
    const installer = model.installer || {};
    const installing = ["queued", "downloading", "installing_runtime"].includes(installer.status);
    const installed = Boolean(installer.installed);
    const needsRuntime = Boolean(installer.weights_installed && installer.runtime_required && !installer.runtime_installed);
    const canInstall = installer.install_supported && installer.compatible && !installing && !installed;
    const stateLabel = model.available
      ? "SẴN SÀNG"
      : installed
        ? "ĐÃ TẢI MODEL"
        : needsRuntime
          ? "THIẾU RUNTIME"
        : installing
          ? `ĐANG TẢI ${installer.progress || 0}%`
          : "CHƯA SẴN SÀNG";
    const buttonLabel = installed
      ? "GỠ MODEL"
      : needsRuntime
        ? "CÀI / SỬA RUNTIME"
      : installing
        ? `ĐANG TẢI ${installer.progress || 0}%`
        : installer.install_supported
          ? "↓ TẢI MODEL"
          : "KHÔNG HỖ TRỢ TỰ ĐỘNG";
    return `
    <article class="free-model-card ${model.available ? "ready" : ""} ${installing ? "installing" : ""}">
      <div class="free-model-topline">
        <span class="free-model-category">${escapeHtml(model.category)}</span>
        <span class="free-model-state ${model.available ? "ready" : installed ? "installed" : installing ? "installing" : ""}"><i></i>${escapeHtml(stateLabel)}</span>
      </div>
      <h3>${escapeHtml(model.name)}</h3>
      <p>${escapeHtml(model.model)}</p>
      <small>${escapeHtml(model.requirements)}</small>
      <code>${escapeHtml(model.tool)} · ${escapeHtml(model.cost)}</code>
      ${installer.id ? `
        <div class="model-install-meta">
          <span>${escapeHtml(installer.size_label || "—")}</span>
          <span>RAM ${escapeHtml(installer.min_memory_gb || "—")} GB+</span>
          <span>${escapeHtml(installer.license || "Không rõ giấy phép")}</span>
        </div>
        ${installing ? `<div class="model-progress"><i style="width:${Math.max(2, installer.progress || 0)}%"></i></div>` : ""}
        <button class="model-install-button ${installed ? "remove" : ""}" type="button" ${installed ? "data-model-remove" : needsRuntime ? "data-model-runtime" : "data-model-install"}="${escapeHtml(installer.id)}" data-license-restricted="${installer.commercial_restricted ? "true" : "false"}" ${canInstall || installed || needsRuntime ? "" : "disabled"}>${escapeHtml(buttonLabel)}</button>
        ${installer.license_url ? `<a class="model-license-link" href="${escapeHtml(installer.license_url)}" target="_blank" rel="noreferrer">XEM GIẤY PHÉP ↗</a>` : ""}
        <div class="model-install-detail ${installer.status === "error" || installer.blocked_reason ? "error" : ""}">${escapeHtml(installer.blocked_reason || installer.detail || (installed && !model.available ? "Model đã tải; runtime tương ứng cần được cài hoặc khởi động." : ""))}</div>
      ` : ""}
    </article>
  `;
  }).join("");

  const active = freeModelCatalog.some((model) => ["queued", "downloading", "installing_runtime"].includes(model.installer?.status));
  if (active && !modelPollTimer) {
    modelPollTimer = window.setInterval(() => refreshFreeModels().catch(console.error), 1200);
  } else if (!active && modelPollTimer) {
    window.clearInterval(modelPollTimer);
    modelPollTimer = null;
  }
}

async function refreshFreeModels() {
  freeModelCatalog = await fetch("/api/free-models").then((response) => {
    if (!response.ok) throw new Error("Không đọc được trạng thái model");
    return response.json();
  });
  renderFreeModels();
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
    runtimeCard("uv / Model Runtime", runtime.uv),
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

freeModels.addEventListener("click", async (event) => {
  const runtimeButton = event.target.closest("button[data-model-runtime]");
  if (runtimeButton && !runtimeButton.disabled) {
    const modelId = runtimeButton.dataset.modelRuntime;
    runtimeButton.disabled = true;
    setStatus("Đang cài / sửa model runtime…");
    try {
      const response = await fetch(`/api/model-installs/${encodeURIComponent(modelId)}/runtime`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Không sửa được runtime");
      setStatus("Đã bắt đầu cài model runtime.", "success");
      await refreshFreeModels();
    } catch (error) {
      setStatus(error.message || "Không sửa được runtime", "error");
      await refreshFreeModels().catch(console.error);
    }
    return;
  }
  const removeButton = event.target.closest("button[data-model-remove]");
  if (removeButton && !removeButton.disabled) {
    const modelId = removeButton.dataset.modelRemove;
    const model = freeModelCatalog.find((item) => item.installer?.id === modelId);
    if (!window.confirm(`Gỡ ${model?.installer?.label || modelId} và runtime riêng khỏi máy này?`)) return;
    removeButton.disabled = true;
    setStatus("Đang gỡ model…");
    try {
      const response = await fetch(`/api/model-installs/${encodeURIComponent(modelId)}`, { method: "DELETE" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Không gỡ được model");
      setStatus("Đã gỡ model khỏi máy.", "success");
      await refreshFreeModels();
    } catch (error) {
      setStatus(error.message || "Không gỡ được model", "error");
      await refreshFreeModels().catch(console.error);
    }
    return;
  }
  const button = event.target.closest("button[data-model-install]");
  if (!button || button.disabled) return;
  const modelId = button.dataset.modelInstall;
  const model = freeModelCatalog.find((item) => item.installer?.id === modelId);
  const installer = model?.installer;
  if (!installer) return;
  const restricted = button.dataset.licenseRestricted === "true";
  const message = restricted
    ? `Model này dùng giấy phép ${installer.license} và có thể không phù hợp mục đích thương mại. Bạn xác nhận đã đọc và chấp nhận giấy phép để tải ${installer.size_label}?`
    : `Tải ${installer.label} (${installer.size_label}) về máy này? App sẽ giữ ít nhất 12 GB dung lượng trống dự phòng.`;
  if (!window.confirm(message)) return;
  button.disabled = true;
  setStatus(`Đang chuẩn bị tải ${installer.label}…`);
  try {
    const response = await fetch(`/api/model-installs/${encodeURIComponent(modelId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accept_license: restricted }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Không bắt đầu tải được model");
    setStatus(`Đã bắt đầu tải ${installer.label}. Bạn có thể tiếp tục dùng app trong lúc tải.`, "success");
    await refreshFreeModels();
  } catch (error) {
    setStatus(error.message || "Không tải được model", "error");
    await refreshFreeModels().catch(console.error);
  }
});

document.querySelector(".model-tier-filter")?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-model-tier]");
  if (!button) return;
  selectedModelTier = button.dataset.modelTier;
  document.querySelectorAll("button[data-model-tier]").forEach((item) => item.classList.toggle("active", item === button));
  renderFreeModels();
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

loadAppVersion().catch((error) => setStatus(error.message || "Không đọc được phiên bản app", "error"));
checkForUpdate(false).catch((error) => { updateStatus.textContent = error.message || "Không kiểm tra được cập nhật"; });
load().catch((error) => setStatus(error.message || "Không tải được cấu hình", "error"));
