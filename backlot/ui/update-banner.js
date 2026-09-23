const banner = document.createElement("aside");
banner.className = "mosa-update-banner";
banner.setAttribute("role", "status");
banner.hidden = true;
banner.innerHTML = `
  <span class="mosa-update-copy"></span>
  <button class="mosa-update-action" type="button"></button>
  <button class="mosa-update-dismiss" type="button" aria-label="Ẩn thông báo cập nhật">×</button>
`;
document.body.prepend(banner);

const copy = banner.querySelector(".mosa-update-copy");
const action = banner.querySelector(".mosa-update-action");
const dismiss = banner.querySelector(".mosa-update-dismiss");
const busyStates = new Set(["queued", "downloading", "verifying", "waiting", "launching"]);
let pollTimer = null;
let latest = null;

function render(payload) {
  latest = payload;
  const job = payload.job || {};
  const busy = busyStates.has(job.status);
  const version = payload.latest_tag || payload.latest_version || "";
  const dismissed = !busy && sessionStorage.getItem("mosa-update-dismissed") === version;
  banner.hidden = dismissed || (!payload.update_available && !busy && job.status !== "error");
  if (banner.hidden) return;

  if (busy) {
    copy.textContent = `${job.detail || "Đang cập nhật…"} ${job.status === "waiting" ? "" : `${job.progress || 0}%`}`;
  } else if (job.status === "error") {
    copy.textContent = `Cập nhật thất bại: ${job.detail}`;
  } else if (job.status === "ready") {
    copy.textContent = `Bản ${version} đã tải và kiểm tra xong. Mở DMG để hoàn tất cập nhật.`;
  } else if (job.status === "launched") {
    copy.textContent = job.detail || "Đã mở bộ cài cập nhật.";
  } else {
    copy.textContent = `Đã có MOSA TOOL ALL ${version}.`;
  }

  action.hidden = busy || !payload.install_supported;
  action.disabled = busy;
  action.textContent = job.status === "error"
    ? "THỬ LẠI"
    : payload.platform === "macos" ? "MỞ BẢN CẬP NHẬT" : "CÀI NGAY";
  dismiss.hidden = busy;

  if (busy && !pollTimer) {
    pollTimer = window.setInterval(refresh, 1500);
  } else if (!busy && pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/app-update");
    if (response.ok) render(await response.json());
  } catch (error) {
    // Offline checks are retried; the settings page exposes a manual check.
  }
}

action.addEventListener("click", async () => {
  if (!latest) return;
  const prompt = latest.platform === "macos"
    ? "Tải bản mới, kiểm tra SHA-256 và mở DMG? Sau đó kéo app vào Applications."
    : "Tải bản mới, kiểm tra SHA-256 và cài đặt? App sẽ đợi workflow đang chạy hoàn tất.";
  if (!window.confirm(prompt)) return;
  action.disabled = true;
  try {
    const response = await fetch("/api/app-update/install", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Không bắt đầu được cập nhật");
    render(payload);
  } catch (error) {
    copy.textContent = error.message || "Không bắt đầu được cập nhật";
    action.disabled = false;
  }
});

dismiss.addEventListener("click", () => {
  if (latest?.latest_tag) sessionStorage.setItem("mosa-update-dismissed", latest.latest_tag);
  banner.hidden = true;
});

refresh();
window.setInterval(refresh, 15 * 60 * 1000);
