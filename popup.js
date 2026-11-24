const BRIDGE_URL = "http://127.0.0.1:8765";

const bridgeStatusEl = document.getElementById("bridge-status");
const messageEl = document.getElementById("state-message");
const videoPanelEl = document.getElementById("video-panel");
const thumbEl = document.getElementById("video-thumb");
const titleEl = document.getElementById("video-title");
const channelEl = document.getElementById("video-channel");
const qualitySelectEl = document.getElementById("quality-select");
const downloadBtnEl = document.getElementById("download-btn");
const progressWrapEl = document.getElementById("progress-wrap");
const progressFillEl = document.getElementById("progress-fill");
const progressTextEl = document.getElementById("progress-text");

let currentVideoUrl = "";
let pollTimer = null;

function setBridgeBadge(ok, text) {
  bridgeStatusEl.textContent = text;
  bridgeStatusEl.className = `badge ${ok ? "badge-ok" : "badge-err"}`;
}

function showMessage(text) {
  videoPanelEl.classList.add("hidden");
  messageEl.classList.remove("hidden");
  messageEl.textContent = text;
}

function isYouTubeVideoUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    const host = parsed.hostname.replace(/^www\./, "");
    if (host === "youtu.be") {
      return parsed.pathname.length > 1;
    }
    if (host === "youtube.com" || host === "m.youtube.com") {
      return (
        (parsed.pathname === "/watch" && parsed.searchParams.has("v")) ||
        parsed.pathname.startsWith("/shorts/")
      );
    }
    return false;
  } catch {
    return false;
  }
}

function formatSize(bytes) {
  if (!bytes || bytes <= 0) return "~";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
}

async function init() {
  try {
    const health = await fetch(`${BRIDGE_URL}/health`);
    if (!health.ok) throw new Error("Bridge offline");
    setBridgeBadge(true, "Bridge Online");
  } catch {
    setBridgeBadge(false, "Bridge Offline");
    showMessage(
      "Local bridge chưa chạy. Hãy mở start_bridge.bat (hoặc python server.py) rồi bấm lại vào extension."
    );
    return;
  }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !isYouTubeVideoUrl(tab.url)) {
    showMessage("Hãy mở một video YouTube (watch hoặc shorts) rồi bấm lại vào extension.");
    return;
  }

  currentVideoUrl = tab.url;
  showMessage("Đang lấy danh sách chất lượng video...");

  try {
    const res = await fetch(
      `${BRIDGE_URL}/formats?url=${encodeURIComponent(currentVideoUrl)}`
    );
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Không thể đọc thông tin video.");
    }

    thumbEl.src = data.thumbnail || "";
    titleEl.textContent = data.title || "YouTube Video";
    channelEl.textContent = data.uploader || "";

    qualitySelectEl.innerHTML = "";
    for (const fmt of data.formats) {
      const opt = document.createElement("option");
      opt.value = fmt.id;
      const sizeStr = fmt.filesize ? ` • ${formatSize(fmt.filesize)}` : "";
      opt.textContent = `${fmt.label}${sizeStr}`;
      qualitySelectEl.appendChild(opt);
    }

    messageEl.classList.add("hidden");
    videoPanelEl.classList.remove("hidden");
  } catch (err) {
    showMessage(`Lỗi: ${err.message}`);
  }
}

async function pollStatus(jobId) {
  try {
    const res = await fetch(`${BRIDGE_URL}/status?job_id=${encodeURIComponent(jobId)}`);
    const job = await res.json();
    if (!res.ok) throw new Error(job.error || "Status error");

    const pct = Math.min(100, Math.max(0, job.progress || 0));
    progressFillEl.style.width = `${pct}%`;

    if (job.state === "downloading" || job.state === "merging") {
      progressTextEl.textContent =
        job.state === "merging"
          ? "Đang ghép video + audio..."
          : `Đang tải: ${pct.toFixed(1)}%`;
      pollTimer = setTimeout(() => pollStatus(jobId), 600);
    } else if (job.state === "done") {
      progressFillEl.style.width = "100%";
      progressTextEl.textContent = `Hoàn tất: ${job.filepath}`;
      downloadBtnEl.disabled = false;
      downloadBtnEl.textContent = "Tải xuống ngay";
    } else if (job.state === "error") {
      progressTextEl.textContent = `Thất bại: ${job.error}`;
      downloadBtnEl.disabled = false;
      downloadBtnEl.textContent = "Thử lại";
    }
  } catch (err) {
    progressTextEl.textContent = `Mất kết nối bridge: ${err.message}`;
    downloadBtnEl.disabled = false;
  }
}

downloadBtnEl.addEventListener("click", async () => {
  if (!currentVideoUrl || !qualitySelectEl.value) return;

  if (pollTimer) clearTimeout(pollTimer);
  downloadBtnEl.disabled = true;
  downloadBtnEl.textContent = "Đang tải...";
  progressWrapEl.classList.remove("hidden");
  progressFillEl.style.width = "0%";
  progressTextEl.textContent = "Đang khởi tạo tiến trình tải...";

  try {
    const res = await fetch(`${BRIDGE_URL}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentVideoUrl,
        format_id: qualitySelectEl.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Không thể bắt đầu tải.");
    pollStatus(data.job_id);
  } catch (err) {
    progressTextEl.textContent = `Lỗi: ${err.message}`;
    downloadBtnEl.disabled = false;
    downloadBtnEl.textContent = "Tải xuống ngay";
  }
});

init();
