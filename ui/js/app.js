/**
 * PLADAZ Frontend Application Controller (Phase 4 & Phase 5 QA Hardened — All 19 Approved Boards: 01–11, 13–20)
 * Strictly enforces:
 * - 4 Task Statuses: Queued, Downloading, Completed, Failed (DEC-025)
 * - 10 Pipeline Stages inside Downloading
 * - No Cover as a warning badge (! NO COVER), never a 5th status
 * - Board 12 (Picker) excluded per user decision (all playlist/album tracks enqueue directly)
 * - Minimum 12px font size, segmented progress bars, dark navy Failed badge (✕ Failed), speech bubble with tail
 */
(function () {
  "use strict";

  const STAGES = [
    { key: "checking_sd", num: "01", short: "CARD", title: "Checking Micro SD Card & Free Space" },
    { key: "fetching_info", num: "02", short: "FETCH", title: "Fetching Track Info from YouTube" },
    { key: "resolving_metadata", num: "03", short: "META", title: "Resolving Metadata & 800×800 Cover Art" },
    { key: "checking_duplicate", num: "04", short: "DUPE?", title: "Checking Target Path & Duplicates" },
    { key: "waiting_conflict", num: "05", short: "CONFLICT", title: "Waiting for Duplicate Conflict Choice" },
    { key: "downloading_stream", num: "06", short: "STREAM", title: "Downloading Audio Stream to Temp" },
    { key: "processing_audio", num: "07", short: "AAC", title: "FFmpeg Remux / Encode to AAC-LC (.m4a)" },
    { key: "tagging", num: "08", short: "TAG", title: "Writing 9 MP4 Metadata Atoms (mutagen)" },
    { key: "validating", num: "09", short: "VERIFY", title: "OutputValidator Pre-Copy Gate" },
    { key: "copying", num: "10", short: "COPY", title: "Copy & Verify to Micro SD Card (fsync)" },
  ];

  const STAGE_INDEX = {};
  STAGES.forEach((s, idx) => {
    STAGE_INDEX[s.key] = idx;
  });

  const state = {
    currentView: "queue",
    version: "1.0.0",
    config: {
      disclaimer_accepted: false,
      destination_path: "",
      cookies_file_path: null,
      require_album_art: false,
      musicbrainz_user_agent: "",
    },
    sdStatus: null,
    removableDrives: [],
    queue: [],
    queueRunning: false,
    queueHalted: false,
    ytdlpStatus: { present: true, version: null, expected_path: "yt-dlp.exe" },
    ytdlpUpdating: false,
    systemInfo: {},
    sdAlert: null,
    systemAlert: null,
    selectedTrackId: null,
    stageModalTaskId: null,
    pendingCancelTaskId: null,
    pendingConflict: null,
    historyEntries: [],
    historyFilter: "all",
    coverCache: {},
    coverLoading: {},
    hadActiveRun: false,
    activeRunTaskIds: new Set(),
    browserDetection: null,
    browserCookies: { enabled: false, browser: null, browser_label: null },
    pendingConsentBrowser: null,
  };

  function escapeHtml(val) {
    if (val === null || val === undefined) return "";
    return String(val)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatBytes(bytes) {
    const num = Number(bytes || 0);
    if (!num || num <= 0) return "0.0 GB";
    const gb = num / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)} GB`;
    const mb = num / (1024 * 1024);
    return `${mb.toFixed(0)} MB`;
  }

  // Backend sends has_cover on TaskDTO and HistoryEntryDTO; null/undefined means unknown, so no badge.
  function hasNoCoverWarning(taskOrHistory) {
    return Boolean(taskOrHistory && taskOrHistory.status === "Completed" && taskOrHistory.has_cover === false);
  }

  function getTaskDisplayTitle(task) {
    if (task && task.metadata && task.metadata.title) {
      return task.metadata.title;
    }
    return task ? task.entry_url : "Track";
  }

  // Screen-reader announcement through the polite live region (UX-02, WCAG 4.1.3)
  function announce(message) {
    const region = document.getElementById("sr-status");
    if (!region || !message) return;
    region.textContent = "";
    region.textContent = String(message);
  }

  // Dialog focus: move focus into a dialog when it opens and give it back to the opener when it closes (UX-09)
  const MODAL_INITIAL_FOCUS = {
    "modal-conflict": "conflict-scope-single",
    "modal-cancel-confirm": "cancel-confirm-no-btn",
    "modal-clear-history": "clear-history-no-btn",
    "modal-disclaimer": "disclaimer-accept-checkbox",
    "modal-ytdlp-setup": "setup-download-btn",
    "modal-updater": "updater-run-btn",
    "modal-error-log": "error-log-done-btn",
    "modal-about": "about-back-btn",
    "modal-queue-summary": "summary-done-btn",
    "modal-task-stages": "task-stages-close-btn",
    "modal-browser-consent": "browser-consent-cancel-btn",
  };
  const modalReturnFocus = {};

  function openModal(id, focusId) {
    const modal = document.getElementById(id);
    if (!modal) return;
    const wasHidden = modal.classList.contains("hidden");
    modal.classList.remove("hidden");
    if (!wasHidden) return;
    modalReturnFocus[id] = document.activeElement || null;
    const target = document.getElementById(focusId || MODAL_INITIAL_FOCUS[id]);
    if (target && typeof target.focus === "function") target.focus();
  }

  function closeModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    const wasOpen = !modal.classList.contains("hidden");
    modal.classList.add("hidden");
    const back = modalReturnFocus[id];
    delete modalReturnFocus[id];
    if (wasOpen && back && typeof back.focus === "function") back.focus();
  }

  function reportCommandError(res, fallbackMessage) {
    if (res && (res.success || res.cancelled)) return false;
    const err = (res && res.error) || {
      code: "ERR_COMMAND_FAILED",
      message_en: (res && res.message) || fallbackMessage || "Command failed.",
      recoverable: true,
    };
    state.systemAlert = err;
    renderGlobalAlerts();
    return true;
  }

  function syncQueueFlagsFromPayload(payload) {
    if (!payload || typeof payload !== "object") return;
    if (typeof payload.queue_running === "boolean") {
      state.queueRunning = payload.queue_running;
    }
    if (typeof payload.queue_halted === "boolean") {
      state.queueHalted = payload.queue_halted;
    }
  }

  function reconstructConflictFromQueue() {
    const waitingTask = state.queue.find((t) => t.stage === "waiting_conflict");
    if (!waitingTask) return null;
    const meta = waitingTask.metadata || {};
    return {
      task_id: waitingTask.task_id,
      existing_path: waitingTask.target_file_path || "",
      metadata_summary: {
        title: meta.title || "",
        album_artist: meta.album_artist || null,
        album: meta.album || null,
      },
    };
  }

  function renderSegmentsHtml(pct, totalSegments = 10, heightClass = "h-2.5") {
    const clamped = Math.max(0, Math.min(100, Number(pct || 0)));
    const filled = clamped >= 100 ? totalSegments : Math.floor((clamped / 100) * totalSegments);
    return Array.from({ length: totalSegments })
      .map((_, i) => {
        const isFilled = i < filled || (clamped > 0 && filled === 0 && i === 0);
        return `<div data-seg-idx="${i}" class="${heightClass} rounded-sm border border-[var(--ink)] ${isFilled ? "bg-[var(--hot)]" : "bg-[var(--soft)]"}"></div>`;
      })
      .join("");
  }

  async function ensureCoverLoaded(taskId) {
    if (!taskId) return null;
    if (state.coverCache[taskId]) return state.coverCache[taskId];
    if (state.coverLoading[taskId]) {
      await state.coverLoading[taskId];
      if (state.coverCache[taskId]) return state.coverCache[taskId];
    }
    const fetchPromise = (async () => {
      try {
        const res = await window.PladazBridge.getCoverPreview(taskId);
        if (res && res.success && res.data_url) {
          state.coverCache[taskId] = res.data_url;
          renderNowProcessing();
          if (state.currentView === "track" && state.selectedTrackId === taskId) {
            renderTrackDetailView();
          }
          return state.coverCache[taskId];
        }
      } finally {
        if (state.coverLoading[taskId] === fetchPromise) {
          delete state.coverLoading[taskId];
        }
      }
      return null;
    })();
    state.coverLoading[taskId] = fetchPromise;
    return fetchPromise;
  }

  // =========================================================================
  // NAVIGATION & VIEWS
  // =========================================================================
  function switchView(viewName) {
    state.currentView = viewName;
    const views = ["queue", "track", "storage", "settings", "history"];
    views.forEach((v) => {
      const el = document.getElementById(`view-${v}`);
      if (el) {
        el.classList.toggle("hidden", v !== viewName);
      }
    });

    document.querySelectorAll(".nav-btn").forEach((btn) => {
      const target = btn.getAttribute("data-nav");
      const active = target === viewName || (viewName === "track" && target === "queue");
      btn.classList.toggle("hot", active);
      btn.setAttribute("aria-current", active ? "page" : "false");
    });

    if (viewName === "history") {
      loadAndRenderHistory();
    } else if (viewName === "storage") {
      renderStorageView();
    } else if (viewName === "settings") {
      populateSettingsForm();
    } else if (viewName === "track") {
      renderTrackDetailView();
    }
  }

  // =========================================================================
  // GLOBAL ALERTS (Board 08: SD Card Disconnected & System Error)
  // =========================================================================
  function renderGlobalAlerts() {
    const container = document.getElementById("global-alerts-container");
    if (!container) return;
    const htmlParts = [];

    if (state.sdAlert) {
      htmlParts.push(`
        <div class="rounded-2xl border-[2.5px] border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 shadow-[0_3px_0_#2B2540]">
          <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1 min-w-0">
            <span class="sil text-xs px-2 py-0.5 rounded bg-[var(--ink)] text-white font-bold shrink-0">! SD CARD ALERT</span>
            <span class="mono text-xs font-bold shrink-0">${escapeHtml(state.sdAlert.code)}</span>
            <span class="text-xs font-medium break-words min-w-0 selectable">${escapeHtml(state.sdAlert.message_en)}</span>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" data-action="alert-resume-queue" class="pbtn hot text-xs">↻ RESUME QUEUE</button>
            <button type="button" data-action="dismiss-sd-alert" class="ibtn" aria-label="Dismiss SD card alert">×</button>
          </div>
        </div>
      `);
    }

    if (state.systemAlert) {
      htmlParts.push(`
        <div class="rounded-2xl border-[2.5px] border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)] px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 shadow-[0_3px_0_#2B2540]">
          <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1 min-w-0">
            <span class="sil text-xs px-2 py-0.5 rounded bg-[var(--ink)] text-white font-bold shrink-0">SYSTEM NOTICE</span>
            <span class="mono text-xs font-bold shrink-0">${escapeHtml(state.systemAlert.code)}</span>
            <span class="text-xs font-medium break-words min-w-0 selectable">${escapeHtml(state.systemAlert.message_en)}</span>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" data-action="open-error-log" class="pbtn text-xs">VIEW DETAILS</button>
            <button type="button" data-action="dismiss-sys-alert" class="ibtn" aria-label="Dismiss system notice">×</button>
          </div>
        </div>
      `);
    }

    container.innerHTML = htmlParts.join("");
    const alertKey = [state.sdAlert && state.sdAlert.code, state.systemAlert && state.systemAlert.code].join("|");
    if (alertKey !== state.lastAnnouncedAlert) {
      state.lastAnnouncedAlert = alertKey;
      if (state.sdAlert) announce(`SD card alert: ${state.sdAlert.message_en}`);
      else if (state.systemAlert) announce(`System notice: ${state.systemAlert.message_en}`);
    }
  }

  // =========================================================================
  // VIEW 01: QUEUE & STORAGE GATE & NOW PROCESSING (Boards 01, 08, 10, 13, 19)
  // =========================================================================
  function isStorageReady() {
    const dest = (state.config && state.config.destination_path || "").trim();
    if (!dest) return false;
    if (!state.sdStatus) return false;
    return Boolean(state.sdStatus.is_connected && state.sdStatus.is_writable);
  }

  function renderStorageGateBanner() {
    const banner = document.getElementById("storage-gate-banner");
    const sdPill = document.getElementById("queue-sd-pill");
    if (!banner || !sdPill) return;

    const dest = (state.config && state.config.destination_path || "").trim();
    const ready = isStorageReady();

    if (!dest || !ready) {
      sdPill.textContent = "SD: NOT READY";
      sdPill.className = "sil text-xs px-2.5 py-1 rounded-full border-2 border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)] font-bold";
      banner.classList.remove("hidden");
      banner.innerHTML = `
        <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)] p-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <div class="sil text-xs font-bold">! NO MICRO SD CARD DESTINATION</div>
            <p class="text-xs">Select a writable folder on your Micro SD Card before starting the download queue.</p>
          </div>
          <button type="button" data-action="quick-choose-folder" class="pbtn hot text-xs">CHOOSE FOLDER…</button>
        </div>
      `;
      return;
    }

    const label = state.sdStatus.volume_label || state.sdStatus.drive_root || "READY";
    sdPill.textContent = `SD: ${label} (${formatBytes(state.sdStatus.free_bytes)} FREE)`;
    sdPill.className = "sil text-xs px-2.5 py-1 rounded-full border-2 border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] font-bold";
    banner.classList.add("hidden");
    banner.innerHTML = "";
  }

  function updateTaskRowProgress(task) {
    if (!task || !task.task_id) return;
    const listEl = document.getElementById("queue-list-container");
    if (!listEl) return;
    const rowEl = listEl.querySelector(`[data-task-row-id="${task.task_id}"]`);
    if (!rowEl) return;

    const stObj = STAGES.find((s) => s.key === task.stage);
    const stText = stObj ? `STAGE ${stObj.num}/10 · ${stObj.key}` : "preparing…";
    const pct = Math.round(Number(task.progress_percent || 0));

    const stageTextEl = rowEl.querySelector("[data-task-stage-text]");
    if (stageTextEl) stageTextEl.textContent = stText;

    const pctTextEl = rowEl.querySelector("[data-task-pct-text]");
    if (pctTextEl) pctTextEl.textContent = `${pct}%`;

    const segContainer = rowEl.querySelector("[data-task-progress-segments]");
    if (segContainer) {
      segContainer.setAttribute("aria-valuenow", String(pct));
      const segNodes = segContainer.querySelectorAll("[data-seg-idx]");
      const totalSegments = segNodes.length || 10;
      const clamped = Math.max(0, Math.min(100, pct));
      const filled = clamped >= 100 ? totalSegments : Math.floor((clamped / 100) * totalSegments);
      segNodes.forEach((node, i) => {
        const isFilled = i < filled || (clamped > 0 && filled === 0 && i === 0);
        node.classList.toggle("bg-[var(--hot)]", isFilled);
        node.classList.toggle("bg-[var(--soft)]", !isFilled);
      });
    }
  }

  function renderQueueList() {
    const counts = { Queued: 0, Downloading: 0, Completed: 0, Failed: 0 };
    state.queue.forEach((t) => {
      if (counts[t.status] !== undefined) counts[t.status] += 1;
      if (t.has_cover && !state.coverCache[t.task_id]) {
        ensureCoverLoaded(t.task_id);
      }
    });

    document.getElementById("count-queued").textContent = String(counts.Queued);
    document.getElementById("count-downloading").textContent = String(counts.Downloading);
    document.getElementById("count-completed").textContent = String(counts.Completed);
    document.getElementById("count-failed").textContent = String(counts.Failed);
    document.getElementById("header-queue-count").textContent = `${counts.Queued + counts.Downloading} IN QUEUE`;

    const vinylDot = document.getElementById("header-vinyl-dot");
    if (vinylDot) {
      vinylDot.classList.toggle("blink", counts.Downloading > 0);
    }

    const clearBtn = document.getElementById("clear-completed-btn");
    if (clearBtn) {
      clearBtn.disabled = counts.Completed === 0;
    }

    const startBtn = document.getElementById("start-queue-btn");
    const resumeBtn = document.getElementById("resume-queue-btn");
    const cancelBtn = document.getElementById("cancel-active-btn");

    const hasQueued = counts.Queued > 0;
    const hasDownloading = counts.Downloading > 0;
    const sdReady = isStorageReady();

    if (startBtn) {
      // Board 16 Decision #5: Disable Start Queue while yt-dlp.exe is updating
      startBtn.disabled = !hasQueued || hasDownloading || !sdReady || state.ytdlpUpdating;
      startBtn.classList.toggle("hidden", state.queueHalted && hasQueued && !hasDownloading);
    }
    if (resumeBtn) {
      const showResume = state.queueHalted && hasQueued && !hasDownloading;
      resumeBtn.classList.toggle("hidden", !showResume);
      resumeBtn.disabled = !sdReady || state.ytdlpUpdating;
    }
    if (cancelBtn) {
      cancelBtn.disabled = !hasDownloading;
    }

    const runHint = document.getElementById("queue-run-hint");
    if (runHint) {
      let hint = "READY · PRESS START QUEUE";
      if (hasDownloading) hint = "SEQUENTIAL WORKER · 1 TRACK AT A TIME";
      else if (state.ytdlpUpdating) hint = "START WAITS · YT-DLP IS UPDATING";
      else if (!hasQueued) hint = "NOTHING TO START · ADD A LINK ABOVE";
      else if (!sdReady) hint = "START NEEDS A WRITABLE MICRO SD FOLDER";
      else if (state.queueHalted) hint = "QUEUE STOPPED · PRESS RESUME QUEUE";
      runHint.textContent = hint;
    }

    const listEl = document.getElementById("queue-list-container");
    if (!listEl) return;

    if (state.queue.length === 0) {
      listEl.innerHTML = `
        <div class="rounded-2xl border-2 border-dashed border-[var(--line)] bg-[var(--soft)] p-8 text-center space-y-2">
          <div class="w-12 h-12 mx-auto rounded-full border-[2.5px] border-[var(--ink)] bg-[var(--chip)] flex items-center justify-center sil text-base text-[var(--violet)]">♫</div>
          <h3 class="dela text-sm text-[var(--ink)]">The turntable is empty</h3>
          <p class="text-xs text-[var(--violet-2)] max-w-md mx-auto">
            Paste a YouTube or YouTube Music track, playlist, or album link above to queue songs for your SNOWSKY ECHO DAP.
          </p>
        </div>
      `;
      return;
    }

    listEl.innerHTML = state.queue
      .map((t, index) => {
        const title = getTaskDisplayTitle(t);
        const artist = (t.metadata && (t.metadata.album_artist || t.metadata.track_artist)) || "YouTube Music";
        const album = (t.metadata && t.metadata.album) || "";
        const subline = album ? `${artist} · ${album}` : artist;

        let statusBadge = "";
        if (t.status === "Queued") {
          statusBadge = `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--chip)] text-[var(--violet)] font-bold">Queued</span>`;
        } else if (t.status === "Downloading") {
          statusBadge = `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--accent)] text-white font-bold">Downloading</span>`;
        } else if (t.status === "Completed") {
          statusBadge = `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] font-bold">✓ Completed</span>`;
        } else if (t.status === "Failed") {
          statusBadge = `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--ink)] text-white font-bold">✕ Failed</span>`;
        }

        const noCoverBadge = hasNoCoverWarning(t)
          ? `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--warn-bd)] bg-[var(--warn)] text-[var(--warn-ink)] font-bold">! No cover</span>`
          : "";

        let stageOrErrorRow = "";
        if (t.status === "Downloading") {
          const stObj = STAGES.find((s) => s.key === t.stage);
          const stText = stObj ? `STAGE ${stObj.num}/10 · ${stObj.key}` : "preparing…";
          const pct = Math.round(Number(t.progress_percent || 0));
          stageOrErrorRow = `
            <div class="mt-2 space-y-1">
              <div class="flex items-center justify-between mono text-xs text-[var(--violet)]">
                <span data-task-stage-text>${escapeHtml(stText)}</span>
                <span data-task-pct-text class="font-bold">${pct}%</span>
              </div>
              <div data-task-progress-segments role="progressbar" aria-label="Progress for ${escapeHtml(title)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" class="grid grid-cols-10 gap-1 p-0.5 rounded border border-[var(--ink)] bg-[var(--paper)]">
                ${renderSegmentsHtml(pct, 10, "h-2")}
              </div>
            </div>
          `;
        } else if (t.status === "Failed" && t.error) {
          stageOrErrorRow = `
            <div class="mt-1.5 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[var(--err)] px-2.5 py-1 border border-[var(--ink)] text-[var(--err-ink)]">
              <span class="mono text-xs font-bold">${escapeHtml(t.error.code)}: ${escapeHtml(t.error.message_en)}</span>
              <div class="flex items-center gap-1">
                <button type="button" data-action="view-task-error" data-task-id="${escapeHtml(t.task_id)}" class="pbtn text-xs py-0.5 px-1.5">LOG</button>
                <button type="button" data-action="retry-task" data-task-id="${escapeHtml(t.task_id)}" class="pbtn hot text-xs py-0.5 px-2">↻ RETRY</button>
              </div>
            </div>
          `;
        }

        return `
          <div data-task-row-id="${escapeHtml(t.task_id)}" class="rounded-xl border-2 border-[var(--ink)] ${t.status === "Downloading" ? "bg-[var(--soft)] ring-2 ring-[var(--hot)]" : "bg-white"} p-2.5 transition">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2.5 min-w-0 flex-1">
                <span class="mono text-xs font-bold px-2 py-1 rounded-lg bg-[var(--chip)] border border-[var(--ink)] text-[var(--violet)] shrink-0">
                  ${String(index + 1).padStart(2, "0")}
                </span>
                <div class="min-w-0 flex-1">
                  <div class="font-bold text-xs sm:text-sm text-[var(--ink)] truncate">${escapeHtml(title)}</div>
                  <div class="text-xs text-[var(--violet-2)] truncate">${escapeHtml(subline)}</div>
                </div>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                ${noCoverBadge}
                ${statusBadge}
                <button type="button" class="ibtn" title="10-Stage Pipeline Detail" aria-label="Show 10 stages for ${escapeHtml(title)}" data-action="open-stages" data-task-id="${escapeHtml(t.task_id)}">▾</button>
                <button type="button" class="ibtn" title="Track Metadata & Validator Details" aria-label="Track details for ${escapeHtml(title)}" data-action="open-track" data-task-id="${escapeHtml(t.task_id)}">→</button>
                <button type="button" class="ibtn" title="${t.status === "Downloading" ? "Cancel Download" : "Remove from Queue"}" aria-label="${t.status === "Downloading" ? `Cancel download of ${escapeHtml(title)}` : `Remove ${escapeHtml(title)} from queue`}" data-action="remove-or-cancel" data-task-id="${escapeHtml(t.task_id)}">×</button>
              </div>
            </div>
            ${stageOrErrorRow}
          </div>
        `;
      })
      .join("");
  }

  function renderNowProcessing() {
    const activeTask =
      state.queue.find((t) => t.status === "Downloading") ||
      state.queue.find((t) => t.status === "Queued") ||
      state.queue[state.queue.length - 1] ||
      null;

    const disc = document.getElementById("turntable-disc");
    const liveDot = document.getElementById("deck-live-dot");
    const stageCounter = document.getElementById("deck-stage-counter");
    const statusBadge = document.getElementById("deck-status-badge");
    const eq = document.getElementById("deck-eq");
    const titleEl = document.getElementById("deck-track-title");
    const artistEl = document.getElementById("deck-track-artist");
    const albumEl = document.getElementById("deck-track-album");
    const stageLabel = document.getElementById("deck-stage-label");
    const pctEl = document.getElementById("deck-progress-pct");
    const segsEl = document.getElementById("deck-progress-segments");
    const speedEtaEl = document.getElementById("deck-speed-eta");
    const openStagesBtn = document.getElementById("deck-open-stages-btn");
    const stageGrid = document.getElementById("deck-stage-grid");
    const mascotEl = document.getElementById("mascot-speech");
    const coverImg = document.getElementById("deck-cover-img");
    const coverFallback = document.getElementById("deck-cover-fallback");

    const isDownloading = Boolean(activeTask && activeTask.status === "Downloading");
    if (disc) {
      disc.classList.toggle("spin-paused", !isDownloading);
    }
    if (liveDot) {
      liveDot.className = isDownloading
        ? "w-2.5 h-2.5 rounded-full bg-[var(--hot)] border border-[var(--ink)] blink"
        : "w-2.5 h-2.5 rounded-full bg-[var(--line)] border border-[var(--ink)]";
    }
    if (eq) {
      eq.classList.toggle("hidden", !isDownloading);
      eq.classList.toggle("flex", isDownloading);
    }

    const activeIdx = activeTask && activeTask.stage && STAGE_INDEX[activeTask.stage] !== undefined
      ? STAGE_INDEX[activeTask.stage]
      : -1;

    if (!activeTask) {
      stageCounter.textContent = "IDLE · 00/10";
      statusBadge.textContent = "STANDBY";
      titleEl.textContent = "Waiting for queue start…";
      artistEl.textContent = "Add a link, then press Start Queue";
      albumEl.textContent = "—";
      stageLabel.textContent = "STAGE: IDLE";
      pctEl.textContent = "0%";
      if (segsEl) {
        segsEl.innerHTML = renderSegmentsHtml(0, 10, "h-2.5");
        segsEl.setAttribute("aria-valuenow", "0");
      }
      speedEtaEl.textContent = "Speed: — · ETA: —";
      openStagesBtn.classList.add("hidden");
      coverImg.classList.add("hidden");
      coverFallback.classList.remove("hidden");
      mascotEl.textContent = "STANDBY · 00/10 — Ready to process AAC-LC (.m4a) tracks to Micro SD.";
    } else {
      const stageNumStr = activeIdx >= 0 ? String(activeIdx + 1).padStart(2, "0") : (activeTask.status === "Completed" ? "10" : "00");
      stageCounter.textContent = `${activeTask.status.toUpperCase()} · ${stageNumStr}/10`;
      statusBadge.textContent = activeTask.status;
      titleEl.textContent = getTaskDisplayTitle(activeTask);
      artistEl.textContent = (activeTask.metadata && (activeTask.metadata.track_artist || activeTask.metadata.album_artist)) || "YouTube Music";
      albumEl.textContent = (activeTask.metadata && activeTask.metadata.album) || "—";

      const stObj = activeIdx >= 0 ? STAGES[activeIdx] : null;
      stageLabel.textContent = stObj ? `STAGE ${stObj.num}: ${stObj.key}` : `STATUS: ${activeTask.status}`;
      const pct = Math.round(Number(activeTask.progress_percent || (activeTask.status === "Completed" ? 100 : 0)));
      pctEl.textContent = `${pct}%`;
      if (segsEl) {
        segsEl.innerHTML = renderSegmentsHtml(pct, 10, "h-2.5");
        segsEl.setAttribute("aria-valuenow", String(pct));
      }
      speedEtaEl.textContent = activeTask._speedEta || "Speed: — · ETA: —";

      openStagesBtn.classList.remove("hidden");
      openStagesBtn.onclick = () => openStageModal(activeTask.task_id);

      const cachedCover = state.coverCache[activeTask.task_id];
      if (cachedCover) {
        coverImg.src = cachedCover;
        coverImg.classList.remove("hidden");
        coverFallback.classList.add("hidden");
      } else {
        coverImg.classList.add("hidden");
        coverFallback.classList.remove("hidden");
      }

      if (activeTask.stage === "waiting_conflict") {
        mascotEl.textContent = `STAGE 05/10 (${pct}%) — Duplicate file conflict waiting for user resolution.`;
      } else if (isDownloading && stObj) {
        mascotEl.textContent = `STAGE ${stObj.num}/10 · ${stObj.key} (${pct}%) — ${stObj.title}`;
      } else if (activeTask.status === "Completed") {
        mascotEl.textContent = "COMPLETED · 10/10 (100%) — Validated by OutputValidator and copied to Micro SD.";
      } else if (activeTask.status === "Failed") {
        mascotEl.textContent = `FAILED (${activeTask.error ? activeTask.error.code : "ERR_FAILED"}) — Task stopped; press Retry to re-queue.`;
      } else {
        mascotEl.textContent = "QUEUED · 00/10 (0%) — Press Start Queue when Micro SD destination is ready.";
      }

      // Mobile mini-player update (Board 19)
      const miniTitle = document.getElementById("mini-player-title");
      const miniStage = document.getElementById("mini-player-stage");
      const miniPct = document.getElementById("mini-player-pct");
      if (miniTitle) miniTitle.textContent = getTaskDisplayTitle(activeTask);
      if (miniStage) miniStage.textContent = stObj ? `STAGE ${stObj.num}: ${stObj.short}` : activeTask.status;
      if (miniPct) miniPct.textContent = `${pct}%`;
    }

    if (stageGrid) {
      stageGrid.innerHTML = STAGES.map((st, idx) => {
        let cls = "bg-[var(--soft)] text-[var(--violet-2)]";
        if (activeTask && activeTask.status === "Completed") {
          cls = "bg-[var(--mint)] text-[var(--mint-ink)] font-bold";
        } else if (activeIdx > idx) {
          cls = "bg-[var(--mint)] text-[var(--mint-ink)] font-bold";
        } else if (activeIdx === idx) {
          cls = "bg-[var(--accent)] text-white font-bold ring-2 ring-[var(--ink)]";
        }
        return `
          <div class="rounded-lg border border-[var(--ink)] px-1.5 py-1 text-center ${cls}" title="${escapeHtml(st.title)}">
            <div class="mono text-xs opacity-85">${st.num}</div>
            <div class="sil text-xs truncate">${st.short}</div>
          </div>
        `;
      }).join("");
    }
  }

  function renderSdCardWidget() {
    const titleEl = document.getElementById("widget-sd-title");
    const pathEl = document.getElementById("widget-sd-path");
    const badgeEl = document.getElementById("widget-sd-badge");
    const segsEl = document.getElementById("widget-sd-segments");
    const freeEl = document.getElementById("widget-sd-free");
    const totalEl = document.getElementById("widget-sd-total");
    if (!titleEl || !segsEl) return;

    const dest = (state.config && state.config.destination_path || "").trim();
    const sd = state.sdStatus;
    if (!dest || !sd || !sd.is_connected) {
      titleEl.textContent = "No Micro SD Destination";
      pathEl.textContent = dest || "Choose a destination folder in Storage / Settings";
      badgeEl.textContent = dest ? "DISCONNECTED" : "UNSET";
      badgeEl.className = "sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)] font-bold";
      freeEl.textContent = "Free: —";
      totalEl.textContent = "Total: —";
      segsEl.innerHTML = Array.from({ length: 10 })
        .map(() => `<div class="h-2.5 rounded-sm border border-[var(--ink)] bg-[var(--soft)]"></div>`)
        .join("");
      return;
    }

    const usedBytes = Math.max(0, (sd.total_bytes || 0) - (sd.free_bytes || 0));
    const ratio = sd.total_bytes > 0 ? usedBytes / sd.total_bytes : 0;
    const filled = Math.min(10, Math.max(1, Math.round(ratio * 10)));

    titleEl.textContent = `${sd.volume_label || "MICRO SD"} (${sd.drive_root || ""})`;
    pathEl.textContent = dest;
    badgeEl.textContent = sd.is_writable ? "READY" : "READ-ONLY";
    badgeEl.className = sd.is_writable
      ? "sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] font-bold"
      : "sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] font-bold";
    freeEl.textContent = `Free: ${formatBytes(sd.free_bytes)}`;
    totalEl.textContent = `Total: ${formatBytes(sd.total_bytes)}`;

    segsEl.innerHTML = Array.from({ length: 10 })
      .map((_, i) => {
        const active = i < filled;
        return `<div class="h-2.5 rounded-sm border border-[var(--ink)] ${active ? "bg-[var(--header)]" : "bg-[var(--mint)]"}"></div>`;
      })
      .join("");
  }

  // =========================================================================
  // VIEW 02: TRACK METADATA & OUTPUT VALIDATOR (Board 02)
  // =========================================================================
  function openTrackDetailView(taskId) {
    state.selectedTrackId = taskId;
    ensureCoverLoaded(taskId);
    switchView("track");
  }

  function renderTrackDetailView() {
    const task = state.queue.find((t) => t.task_id === state.selectedTrackId);
    if (!task) {
      switchView("queue");
      return;
    }

    const badgesEl = document.getElementById("track-detail-badges");
    const noCover = hasNoCoverWarning(task)
      ? `<span class="sil text-xs px-2.5 py-1 rounded border border-[var(--warn-bd)] bg-[var(--warn)] text-[var(--warn-ink)] font-bold">! NO COVER</span>`
      : "";
    const statusChipCls = task.status === "Failed"
      ? "bg-[var(--ink)] text-white"
      : task.status === "Completed"
      ? "bg-[var(--mint)] text-[var(--mint-ink)]"
      : task.status === "Downloading"
      ? "bg-[var(--accent)] text-white"
      : "bg-[var(--paper)] text-[var(--ink)]";
    const statusLabel = task.status === "Failed" ? "✕ Failed" : task.status === "Completed" ? "✓ Completed" : task.status;
    badgesEl.innerHTML = `
      ${noCover}
      <span class="sil text-xs px-2.5 py-1 rounded border-2 border-[var(--ink)] ${statusChipCls} font-bold">${escapeHtml(statusLabel)}</span>
    `;

    const coverImg = document.getElementById("track-view-cover-img");
    const coverEmpty = document.getElementById("track-view-cover-empty");
    const covrPill = document.getElementById("track-view-covr-pill");
    const cachedCover = state.coverCache[task.task_id];
    if (cachedCover) {
      coverImg.src = cachedCover;
      coverImg.classList.remove("hidden");
      coverEmpty.classList.add("hidden");
    } else {
      coverImg.classList.add("hidden");
      coverEmpty.classList.remove("hidden");
    }

    if (covrPill) {
      covrPill.textContent = task.has_cover
        ? "EMBEDDED ATOM: covr (800×800 JPEG)"
        : "ATOM covr: <omitted — no cover art>";
    }

    const pathStr = task.target_file_path || "Pending path resolution…";
    document.getElementById("track-view-path").textContent = pathStr;
    const lenEl = document.getElementById("track-view-path-len");
    const len = task.target_file_path ? task.target_file_path.length : 0;
    lenEl.textContent = `${len} / 259 chars`;
    lenEl.className = len > 259
      ? "mono text-xs font-bold text-[var(--err-ink)]"
      : "mono text-xs font-bold text-[var(--mint-ink)]";

    const m = task.metadata || {};
    const fields = [
      { label: "1. Title (Required)", atom: "©nam", val: m.title },
      { label: "2. Track Artist", atom: "©ART", val: m.track_artist },
      { label: "3. Album", atom: "©alb", val: m.album },
      { label: "4. Album Artist", atom: "aART", val: m.album_artist },
      { label: "5. Track Number", atom: "trkn", val: m.track_number !== null && m.track_number !== undefined ? String(m.track_number) : null },
      { label: "6. Disc Number", atom: "disk", val: m.disc_number !== null && m.disc_number !== undefined ? String(m.disc_number) : null },
      { label: "7. Release Year", atom: "©day", val: m.year },
      { label: "8. Genre", atom: "©gen", val: m.genre },
      { label: "9. Embedded Cover Art", atom: "covr", val: task.has_cover ? "800 × 800 JPEG (1:1)" : null },
    ];

    document.getElementById("track-metadata-grid").innerHTML = fields
      .map((f) => {
        const present = f.val !== null && f.val !== undefined && String(f.val).trim() !== "";
        return `
          <div class="rounded-xl border-2 border-[var(--ink)] ${present ? "bg-[var(--soft)]" : "bg-white opacity-75"} p-2.5">
            <div class="flex items-center justify-between">
              <span class="sil text-xs font-bold text-[var(--violet)]">${escapeHtml(f.label)}</span>
              <code class="mono text-xs px-1.5 py-0.5 rounded bg-[var(--chip)] border border-[var(--ink)]">${escapeHtml(f.atom)}</code>
            </div>
            <div class="mono text-xs font-bold mt-1 ${present ? "text-[var(--ink)]" : "text-[var(--violet-2)] italic"}">
              ${present ? escapeHtml(f.val) : "&lt;empty — omitted from tag&gt;"}
            </div>
          </div>
        `;
      })
      .join("");

    const v = task.validation;
    const summaryEl = document.getElementById("track-validator-summary");
    if (!v) {
      summaryEl.textContent =
        task.status === "Queued" || task.status === "Downloading"
          ? "WAITING"
          : "NO VALIDATION DATA";
    } else {
      summaryEl.textContent = v.is_valid ? "VALIDATED PASS" : `FAILED (${v.error_code || "INVALID"})`;
    }

    const checks = [
      { name: "1. M4A Container Readable", ok: v ? v.is_readable : null },
      { name: "2. Codec = AAC-LC (mp4a.40.2)", ok: v ? v.is_aac_lc : null },
      { name: "3. Title Tag (©nam) Present", ok: v ? v.has_title : null },
      { name: "4. Cover Art (covr 800×800)", ok: v ? v.has_cover : null, warnOnly: !state.config.require_album_art },
    ];

    document.getElementById("track-validator-checks").innerHTML = checks
      .map((c) => {
        let badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--chip)] border border-[var(--ink)]">PENDING</span>`;
        if (!v) {
          if (task.status === "Completed" || task.status === "Failed") {
            badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--chip)] text-[var(--violet-2)] border border-[var(--ink)] font-bold">NO DATA</span>`;
          }
        } else if (c.ok === true) {
          badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--mint)] text-[var(--mint-ink)] border border-[var(--ink)] font-bold">PASS</span>`;
        } else if (c.warnOnly) {
          badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--warn)] text-[var(--warn-ink)] border border-[var(--ink)] font-bold">! NO COVER</span>`;
        } else {
          badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--ink)] text-white border border-[var(--ink)] font-bold">FAIL</span>`;
        }
        return `
          <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] p-2.5 flex items-center justify-between gap-2">
            <span class="text-xs font-bold text-[var(--ink)]">${escapeHtml(c.name)}</span>
            ${badge}
          </div>
        `;
      })
      .join("");
  }

  // =========================================================================
  // VIEW 03: STORAGE / SD CARD MANAGER (Board 03)
  // =========================================================================
  function renderStorageView() {
    const listEl = document.getElementById("storage-drives-list");
    const capLabel = document.getElementById("storage-cap-label");
    const seg20 = document.getElementById("storage-20-segments");
    const destBox = document.getElementById("storage-dest-path-box");
    const previewRoot = document.getElementById("organizer-preview-root");
    if (!listEl) return;

    const dest = (state.config && state.config.destination_path || "").trim();
    destBox.textContent = dest || "Not configured — click CHOOSE FOLDER…";
    previewRoot.textContent = dest || "E:\\Music";

    if (!state.removableDrives || state.removableDrives.length === 0) {
      listEl.innerHTML = `
        <div class="rounded-xl border-2 border-dashed border-[var(--line)] bg-[var(--soft)] p-3 text-xs text-[var(--violet-2)]">
          No removable drives (<code class="mono">DRIVE_REMOVABLE</code>) detected right now. You can insert a Micro SD card and click <strong>SCAN REMOVABLE DRIVES</strong>, or click <strong>CHOOSE FOLDER…</strong> below to select any accessible destination folder.
        </div>
      `;
    } else {
      listEl.innerHTML = state.removableDrives
        .map((d) => {
          return `
            <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] p-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div class="font-bold text-xs text-[var(--ink)]">${escapeHtml(d.volume_label || "Removable Media")} (${escapeHtml(d.drive_root)})</div>
                <div class="mono text-xs text-[var(--violet-2)]">Free: ${formatBytes(d.free_bytes)} / Total: ${formatBytes(d.total_bytes)}</div>
              </div>
              <button type="button" data-action="select-drive-root" data-drive-root="${escapeHtml(d.drive_root)}" class="pbtn hot text-xs">USE THIS CARD</button>
            </div>
          `;
        })
        .join("");
    }

    const sd = state.sdStatus;
    if (!sd || !sd.is_connected) {
      capLabel.textContent = "Disconnected / Not selected";
      seg20.innerHTML = Array.from({ length: 20 })
        .map(() => `<div class="h-3 rounded-sm border border-[var(--ink)] bg-white"></div>`)
        .join("");
    } else {
      const used = Math.max(0, (sd.total_bytes || 0) - (sd.free_bytes || 0));
      const ratio = sd.total_bytes > 0 ? used / sd.total_bytes : 0;
      const filled = Math.min(20, Math.max(1, Math.round(ratio * 20)));
      capLabel.textContent = `${formatBytes(sd.free_bytes)} FREE / ${formatBytes(sd.total_bytes)} TOTAL`;
      seg20.innerHTML = Array.from({ length: 20 })
        .map((_, idx) => `<div class="h-3 rounded-sm border border-[var(--ink)] ${idx < filled ? "bg-[var(--header)]" : "bg-[var(--mint)]"}"></div>`)
        .join("");
    }
  }

  // =========================================================================
  // VIEW 06: SETTINGS (Board 06)
  // =========================================================================
  function renderBrowserAuthSection() {
    const selectEl = document.getElementById("settings-browser-select");
    const recTagEl = document.getElementById("settings-browser-recommended-tag");
    const statusEl = document.getElementById("settings-browser-status");
    const useBtn = document.getElementById("settings-use-browser-btn");
    const testBtn = document.getElementById("settings-test-browser-btn");
    const removeBtn = document.getElementById("settings-remove-browser-btn");
    if (!selectEl || !statusEl) return;

    const detection = state.browserDetection;
    const configured = state.browserCookies || { enabled: false, browser: null, browser_label: null };
    const browsers = (detection && detection.browsers) || [];
    const recommendedKey = detection ? detection.recommended : null;

    const prevVal = selectEl.value;
    selectEl.innerHTML = "";
    if (browsers.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No supported browser detected";
      opt.disabled = true;
      selectEl.appendChild(opt);
      if (useBtn) useBtn.disabled = true;
      if (testBtn) testBtn.disabled = true;
    } else {
      browsers.forEach((b) => {
        const opt = document.createElement("option");
        opt.value = b.key;
        const hints = [];
        if (b.is_default) hints.push("Default");
        if (b.key === recommendedKey) hints.push("Recommended");
        const suffix = hints.length > 0 ? ` (${hints.join(", ")})` : "";
        opt.textContent = `${b.label}${suffix}`;
        selectEl.appendChild(opt);
      });
      const targetVal = configured.browser || prevVal || recommendedKey || (browsers[0] ? browsers[0].key : "");
      if (targetVal) {
        selectEl.value = targetVal;
      }
      if (useBtn) useBtn.disabled = false;
      if (testBtn) testBtn.disabled = false;
    }

    const currentVal = selectEl.value;
    if (recTagEl) {
      if (currentVal && currentVal === recommendedKey) {
        recTagEl.classList.remove("hidden");
        recTagEl.title = (detection && detection.recommendation_reason) || "Recommended browser";
      } else {
        recTagEl.classList.add("hidden");
      }
    }

    if (configured.enabled && configured.browser) {
      const label = configured.browser_label || configured.browser.toUpperCase();
      statusEl.textContent = `✓ ACTIVE: ${label}`;
      statusEl.className = "mono text-xs px-3 py-1.5 rounded-xl border-2 border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] font-bold";
      if (removeBtn) removeBtn.disabled = false;
    } else if (configured.browser) {
      const label = configured.browser_label || configured.browser.toUpperCase();
      statusEl.textContent = `! INACTIVE: ${label}`;
      statusEl.className = "mono text-xs px-3 py-1.5 rounded-xl border-2 border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)] font-bold";
      if (removeBtn) removeBtn.disabled = false;
    } else {
      statusEl.textContent = "OFF / NOT CONFIGURED";
      statusEl.className = "mono text-xs px-3 py-1.5 rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] text-[var(--violet-2)] font-bold";
      if (removeBtn) removeBtn.disabled = true;
    }
  }

  function setBrowserFeedback(message, nextStep = "", isError = false) {
    const container = document.getElementById("settings-browser-feedback");
    const msgEl = document.getElementById("settings-browser-feedback-msg");
    const stepEl = document.getElementById("settings-browser-feedback-step");
    if (!container || !msgEl || !stepEl) return;

    if (!message) {
      container.classList.add("hidden");
      msgEl.textContent = "";
      stepEl.textContent = "";
      return;
    }

    msgEl.textContent = message;
    stepEl.textContent = nextStep || "";
    container.className = isError
      ? "text-xs space-y-1 p-2.5 rounded-xl border-2 border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)]"
      : "text-xs space-y-1 p-2.5 rounded-xl border-2 border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)]";
    container.classList.remove("hidden");
  }

  function openBrowserConsentModal(browserKey) {
    const key = (browserKey || "").toLowerCase();
    const candidate = state.browserDetection && state.browserDetection.browsers
      ? state.browserDetection.browsers.find((b) => b.key === key)
      : null;
    const label = candidate ? candidate.label : key.toUpperCase();

    state.pendingConsentBrowser = key;
    const targetEl = document.getElementById("browser-consent-target-name");
    const labelEl = document.getElementById("browser-consent-browser-label");
    if (targetEl) targetEl.textContent = label.toUpperCase();
    if (labelEl) labelEl.textContent = label;

    const modal = document.getElementById("modal-browser-consent");
    if (modal) {
      openModal(modal.id);
      const cancelBtn = document.getElementById("browser-consent-cancel-btn");
      if (cancelBtn) cancelBtn.focus();
    }
  }

  function closeBrowserConsentModal() {
    state.pendingConsentBrowser = null;
    const modal = document.getElementById("modal-browser-consent");
    if (modal) closeModal(modal.id);
  }

  function populateSettingsForm() {
    document.getElementById("settings-dest-input").value = state.config.destination_path || "";
    const reqCover = Boolean(state.config.require_album_art);
    const cb = document.getElementById("settings-require-cover-checkbox");
    cb.checked = reqCover;
    document.getElementById("settings-require-cover-label").textContent = reqCover
      ? "ON (STRICT — FAIL IF MISSING)"
      : "OFF (WARN ONLY)";

    const cookiesPath = state.config.cookies_file_path;
    const cookiesName = cookiesPath ? String(cookiesPath).split(/[\\/]/).pop() : "Not selected";
    document.getElementById("settings-cookies-filename").textContent = cookiesName;

    const ytdlpVer = state.ytdlpStatus && state.ytdlpStatus.present
      ? `yt-dlp ${state.ytdlpStatus.version || "ready"}`
      : "Missing yt-dlp.exe";
    document.getElementById("settings-ytdlp-version").textContent = ytdlpVer;

    document.getElementById("settings-mb-ua-input").value = state.config.musicbrainz_user_agent || "";

    if (!state.browserDetection && window.PladazBridge && window.PladazBridge.detectSupportedBrowsers) {
      window.PladazBridge.detectSupportedBrowsers().then((res) => {
        if (res && res.success && res.detection) {
          state.browserDetection = res.detection;
          renderBrowserAuthSection();
        }
      });
    }
    renderBrowserAuthSection();
  }

  // =========================================================================
  // VIEW 07: HISTORY (Board 07)
  // =========================================================================
  async function loadAndRenderHistory() {
    const res = await window.PladazBridge.getHistory();
    if (res && res.success) {
      state.historyEntries = (res.entries || []).slice().reverse();
    } else {
      reportCommandError(res, "Failed to load download history.");
    }
    renderHistoryList();
  }

  function renderHistoryList() {
    const badge = document.getElementById("history-count-badge");
    const listEl = document.getElementById("history-list-container");
    if (!listEl) return;

    badge.textContent = `${state.historyEntries.length} RECORDS`;
    const filtered = state.historyEntries.filter((e) => {
      if (state.historyFilter === "all") return true;
      return e.status === state.historyFilter;
    });

    if (filtered.length === 0) {
      listEl.innerHTML = `
        <div class="rounded-xl border-2 border-dashed border-[var(--line)] bg-[var(--soft)] p-8 text-center text-xs text-[var(--violet-2)]">
          No history records match this filter.
        </div>
      `;
      return;
    }

    listEl.innerHTML = filtered
      .map((entry) => {
        const isOk = entry.status === "Completed";
        const statusChip = isOk
          ? `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] font-bold">✓ Completed</span>`
          : `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--ink)] bg-[var(--ink)] text-white font-bold">✕ Failed</span>`;
        const noCoverChip = hasNoCoverWarning(entry)
          ? `<span class="sil text-xs px-2 py-0.5 rounded border border-[var(--warn-bd)] bg-[var(--warn)] text-[var(--warn-ink)] font-bold">! No cover</span>`
          : "";
        const title = entry.title || entry.source_url || "Track";
        const artistAlbum = [entry.album_artist, entry.album].filter(Boolean).join(" · ") || entry.source_url;
        const subDetail = isOk
          ? (entry.target_file_path || "")
          : `Error: ${entry.error_code || "ERR_FAILED"}`;

        return `
          <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] p-3 flex flex-wrap items-center justify-between gap-2">
            <div class="min-w-0 flex-1">
              <div class="font-bold text-xs sm:text-sm text-[var(--ink)] truncate">${escapeHtml(title)}</div>
              <div class="text-xs text-[var(--violet-2)] truncate">${escapeHtml(artistAlbum)}</div>
              <div class="mono text-xs text-[var(--violet)] truncate mt-0.5 selectable">${escapeHtml(subDetail)}</div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              ${noCoverChip}
              ${statusChip}
              <span class="mono text-xs text-[var(--violet-2)]">${escapeHtml((entry.finished_at || "").slice(0, 19).replace("T", " "))}</span>
            </div>
          </div>
        `;
      })
      .join("");
  }

  // =========================================================================
  // MODALS: BOARDS 04, 05, 09, 11, 14, 15, 16, 17, 20
  // =========================================================================
  function openDisclaimerModal(readOnly = false) {
    const modal = document.getElementById("modal-disclaimer");
    const stepPill = document.getElementById("disclaimer-step-pill");
    const cbRow = document.getElementById("disclaimer-checkbox-row");
    const cb = document.getElementById("disclaimer-accept-checkbox");
    const quitBtn = document.getElementById("disclaimer-quit-btn");
    const closeBtn = document.getElementById("disclaimer-close-readonly-btn");
    const acceptBtn = document.getElementById("disclaimer-accept-btn");

    stepPill.textContent = readOnly ? "READ-ONLY VIEW" : "FIRST LAUNCH · STEP 1 OF 2";
    cbRow.classList.toggle("hidden", readOnly);
    quitBtn.classList.toggle("hidden", readOnly);
    acceptBtn.classList.toggle("hidden", readOnly);
    closeBtn.classList.toggle("hidden", !readOnly);
    cb.checked = Boolean(state.config.disclaimer_accepted);
    acceptBtn.disabled = !cb.checked;

    openModal(modal.id);
  }

  function openYtdlpSetupModal() {
    const modal = document.getElementById("modal-ytdlp-setup");
    document.getElementById("setup-expected-path").textContent =
      (state.ytdlpStatus && state.ytdlpStatus.expected_path) || "[app folder]\\yt-dlp.exe";
    openModal(modal.id);
  }

  function openConflictModal(payload) {
    if (!payload) return;
    state.pendingConflict = payload;
    const modal = document.getElementById("modal-conflict");
    document.getElementById("conflict-existing-path").textContent = payload.existing_path || "—";
    const meta = payload.metadata_summary || {};
    document.getElementById("conflict-new-title").textContent = meta.title || "Track";
    document.getElementById("conflict-new-meta").textContent =
      [meta.album_artist, meta.album].filter(Boolean).join(" · ") || "—";
    const radios = document.querySelectorAll('input[name="conflict-scope"]');
    radios.forEach((r) => {
      r.checked = r.value === "single";
    });
    openModal(modal.id);
  }

  function setUpdaterCloseLocked(locked) {
    ["updater-close-btn", "updater-done-btn"].forEach((id) => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = locked;
    });
    const reason = document.getElementById("updater-close-reason");
    if (reason) reason.classList.toggle("hidden", !locked);
  }

  // Keep Tab / Shift+Tab inside the top-most open dialog (Design Direction accessibility rule)
  function trapFocusInOpenModal(e) {
    if (e.key !== "Tab") return;
    const open = Array.from(document.querySelectorAll(".modal-backdrop")).filter(
      (m) => !m.classList.contains("hidden")
    );
    const modal = open[open.length - 1];
    if (!modal) return;
    const focusable = Array.from(
      modal.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")
    ).filter((el) => !el.disabled && !el.classList.contains("hidden"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) {
      e.preventDefault();
      first.focus();
    }
  }

  function openCancelConfirmModal(taskId) {
    const task = state.queue.find((t) => t.task_id === taskId);
    if (!task) return;
    state.pendingCancelTaskId = taskId;
    document.getElementById("cancel-confirm-track-name").textContent = getTaskDisplayTitle(task);
    const modal = document.getElementById("modal-cancel-confirm");
    openModal(modal.id);
    const noBtn = document.getElementById("cancel-confirm-no-btn");
    if (noBtn) noBtn.focus();
  }

  function openStageModal(taskId) {
    state.stageModalTaskId = taskId;
    renderStageModal();
    openModal("modal-task-stages");
  }

  function renderStageModal() {
    const task = state.queue.find((t) => t.task_id === state.stageModalTaskId);
    if (!task) return;
    document.getElementById("task-stages-title").textContent = getTaskDisplayTitle(task);
    document.getElementById("task-stages-subtitle").textContent = task.entry_url;

    const activeIdx = task.stage && STAGE_INDEX[task.stage] !== undefined ? STAGE_INDEX[task.stage] : -1;
    const stageNum = activeIdx >= 0 ? String(activeIdx + 1).padStart(2, "0") : (task.status === "Completed" ? "10" : "00");
    document.getElementById("task-stages-badge").textContent = `STAGE ${stageNum}/10`;

    document.getElementById("task-stages-list").innerHTML = STAGES.map((st, idx) => {
      let badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--soft)] border border-[var(--ink)]">PENDING</span>`;
      let extraBtn = "";
      if (task.status === "Completed" || (activeIdx > idx)) {
        badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--mint)] text-[var(--mint-ink)] border border-[var(--ink)] font-bold">DONE</span>`;
      } else if (activeIdx === idx) {
        if (st.key === "waiting_conflict") {
          badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--warn)] text-[var(--warn-ink)] border border-[var(--ink)] font-bold">ACTION NEEDED</span>`;
          extraBtn = `<button type="button" data-action="reopen-conflict" class="pbtn hot text-xs py-0.5 px-2">OPEN PROMPT</button>`;
        } else {
          badge = `<span class="sil text-xs px-2 py-0.5 rounded bg-[var(--accent)] text-white border border-[var(--ink)] font-bold">RUNNING</span>`;
        }
      }
      return `
        <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] px-3 py-2 flex items-center justify-between gap-2">
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="mono text-xs font-bold text-[var(--violet)]">${st.num}</span>
            <div class="min-w-0">
              <div class="mono text-xs font-bold text-[var(--ink)]">${escapeHtml(st.key)}</div>
              <div class="text-xs text-[var(--violet-2)] truncate">${escapeHtml(st.title)}</div>
            </div>
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            ${extraBtn}
            ${badge}
          </div>
        </div>
      `;
    }).join("");
  }

  function checkAndShowQueueSummary() {
    if (!state.hadActiveRun) return;
    const anyActive = state.queue.some((t) => t.status === "Queued" || t.status === "Downloading");
    if (anyActive || state.queueHalted) return;

    state.hadActiveRun = false;
    const runTasks =
      state.activeRunTaskIds && state.activeRunTaskIds.size > 0
        ? state.queue.filter((t) => state.activeRunTaskIds.has(t.task_id))
        : state.queue;
    state.activeRunTaskIds = new Set();

    const completed = runTasks.filter((t) => t.status === "Completed");
    const failed = runTasks.filter((t) => t.status === "Failed");
    const noCover = completed.filter((t) => hasNoCoverWarning(t));

    document.getElementById("summary-completed-count").textContent = String(completed.length);
    document.getElementById("summary-failed-count").textContent = String(failed.length);
    document.getElementById("summary-nocover-count").textContent = String(noCover.length);

    const failedList = document.getElementById("summary-failed-list");
    failedList.innerHTML = failed
      .map((f) => `
        <div class="rounded-xl border border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] px-3 py-1.5 flex items-center justify-between gap-2 text-xs">
          <span class="truncate font-bold">${escapeHtml(getTaskDisplayTitle(f))} (${escapeHtml(f.error ? f.error.code : "Failed")})</span>
          <button type="button" data-action="summary-retry" data-task-id="${escapeHtml(f.task_id)}" class="pbtn text-xs py-0.5 px-2">RETRY</button>
        </div>
      `)
      .join("");

    openModal("modal-queue-summary");
  }

  async function openErrorLogModal(errObj) {
    const codeBadge = document.getElementById("error-log-code-badge");
    const msgEl = document.getElementById("error-log-message");
    const termEl = document.getElementById("error-log-terminal");

    codeBadge.textContent = (errObj && errObj.code) || "PLADAZ.LOG";
    msgEl.textContent = (errObj && errObj.message_en) || "Recent diagnostic entries from logs/pladaz.log (cookies and tokens automatically redacted).";
    termEl.innerHTML = `<div class="text-[#9FD4F7]">Loading logs/pladaz.log…</div>`;
    openModal("modal-error-log");

    const res = await window.PladazBridge.getRecentLogs(80);
    if (res && res.success && res.lines && res.lines.length > 0) {
      termEl.innerHTML = res.lines
        .map((line) => {
          let color = "text-[#EEE9FD]";
          if (line.includes("| ERROR |")) color = "text-[#FFB0D9] font-bold";
          else if (line.includes("| WARNING |")) color = "text-[#FFF1C2]";
          return `<div class="${color} break-all">${escapeHtml(line)}</div>`;
        })
        .join("");
      termEl.scrollTop = termEl.scrollHeight;
    } else {
      termEl.innerHTML = `<div class="text-[#9FD4F7]">No log entries recorded yet.</div>`;
    }
  }

  function openAboutModal() {
    document.getElementById("about-version").textContent = `v${state.version || "1.0.0"}`;
    document.getElementById("about-ytdlp-ver").textContent =
      (state.ytdlpStatus && state.ytdlpStatus.version) || "missing";
    document.getElementById("about-ffmpeg-ver").textContent =
      (state.systemInfo && state.systemInfo.ffmpeg_version) || "bundled";
    openModal("modal-about");
  }

  // =========================================================================
  // EVENT LISTENERS & DOM WIRING
  // =========================================================================
  function bindEvents() {
    // Navigation buttons
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.getAttribute("data-nav");
        if (target) switchView(target);
      });
    });

    document.getElementById("brand-home-btn").addEventListener("click", () => switchView("queue"));
    document.getElementById("header-about-btn").addEventListener("click", openAboutModal);
    document.getElementById("track-back-btn").addEventListener("click", () => switchView("queue"));

    // Enqueue Form (Board 01 & Board 13 Fetching feedback)
    const enqueueForm = document.getElementById("enqueue-form");
    const urlInput = document.getElementById("url-input");
    const addUrlBtn = document.getElementById("add-url-btn");
    const addUrlLabel = document.getElementById("add-url-label");
    const feedbackArea = document.getElementById("fetching-feedback-area");

    const growLinkBox = () => {
      if (!urlInput.style) return;
      urlInput.style.height = "auto";
      if (urlInput.scrollHeight) urlInput.style.height = `${urlInput.scrollHeight + 4}px`;
      // Scroll only once the box reaches its max height (160px)
      urlInput.style.overflowY = urlInput.scrollHeight > 160 ? "auto" : "hidden";
    };
    urlInput.addEventListener("input", growLinkBox);
    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        submitLinks();
      }
    });
    enqueueForm.addEventListener("submit", (e) => {
      e.preventDefault();
      submitLinks();
    });

    async function submitLinks() {
      const rawUrl = (urlInput.value || "").trim();
      if (!rawUrl || urlInput.disabled) return;

      urlInput.disabled = true;
      addUrlBtn.disabled = true;
      addUrlLabel.textContent = "READING…";
      feedbackArea.classList.remove("hidden");
      feedbackArea.innerHTML = `
        <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] p-3 space-y-2 skel">
          <div class="sil text-xs text-[var(--violet)] font-bold">READING LINK METADATA VIA YT-DLP…</div>
          <div class="h-3 bg-[var(--line)] rounded w-3/4"></div>
        </div>
      `;

      const res = await window.PladazBridge.enqueueUrls(rawUrl);
      urlInput.disabled = false;
      addUrlBtn.disabled = false;
      addUrlLabel.textContent = "ADD TO QUEUE";

      const addedList = (res && res.tasks_added) || [];
      if (state.hadActiveRun) {
        addedList.forEach((t) => {
          if (t && t.task_id) state.activeRunTaskIds.add(t.task_id);
        });
      }
      const failedLines = (res && res.failed_lines) || [];
      if (!(res && res.success) && failedLines.length === 0) {
        failedLines.push({
          url: rawUrl,
          error: (res && res.error) || { code: "ERR_SOURCE_INVALID_URL", message_en: "Could not read link." },
        });
      }
      // Keep only the lines that failed so a retry never queues the good ones twice
      urlInput.value = failedLines.map((f) => f.url).join("\n");
      growLinkBox();

      const count = addedList.length;
      const addedText = `ADDED ${count} TRACK${count === 1 ? "" : "S"} TO QUEUE`;
      const parts = [];
      if (count > 0 || failedLines.length === 0) {
        parts.push(`
          <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] px-3 py-2 flex items-center justify-between text-xs font-bold">
            <span>✓ ${addedText}</span>
            <button type="button" data-action="dismiss-fetch-feedback" class="ibtn" aria-label="Dismiss message">×</button>
          </div>
        `);
      }
      if (failedLines.length > 0) {
        parts.push(`
          <div class="rounded-xl border-2 border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] p-3 flex items-start justify-between gap-2 text-xs">
            <div class="space-y-1.5 min-w-0 selectable">
              <div class="font-bold">${failedLines.length === 1 ? "This link could not be added:" : `${failedLines.length} links could not be added:`}</div>
              ${failedLines.map((f) => `
                <div>
                  <div class="mono break-all">${escapeHtml(f.url)}</div>
                  <div><span class="mono font-bold">${escapeHtml(f.error && f.error.code)}</span> · ${escapeHtml(f.error && f.error.message_en)}</div>
                </div>`).join("")}
              <div class="text-[var(--ink)]">The failed lines stay in the box so you can fix them and press Enter again.</div>
            </div>
            <button type="button" data-action="dismiss-fetch-feedback" class="ibtn" aria-label="Dismiss message">×</button>
          </div>
        `);
      }
      feedbackArea.innerHTML = parts.join("");
      announce(
        failedLines.length === 0
          ? `Added ${count} track${count === 1 ? "" : "s"} to the queue.`
          : `Added ${count} track${count === 1 ? "" : "s"}. ${failedLines.length} link${failedLines.length === 1 ? "" : "s"} could not be added.`
      );
    }

    // Queue Controls (strictly rely on Backend response/events for queueRunning and queueHalted)
    document.getElementById("start-queue-btn").addEventListener("click", async () => {
      const queuedIds = state.queue
        .filter((t) => t.status === "Queued" || t.status === "Downloading")
        .map((t) => t.task_id);
      state.activeRunTaskIds = new Set(queuedIds);
      state.hadActiveRun = queuedIds.length > 0;

      const res = await window.PladazBridge.startQueue();
      if (reportCommandError(res, "Failed to start download queue.")) {
        state.hadActiveRun = false;
        state.activeRunTaskIds = new Set();
        return;
      }
      syncQueueFlagsFromPayload(res);
      renderQueueList();
    });

    document.getElementById("resume-queue-btn").addEventListener("click", async () => {
      state.queue
        .filter((t) => t.status === "Queued" || t.status === "Downloading")
        .forEach((t) => state.activeRunTaskIds.add(t.task_id));
      state.hadActiveRun = state.activeRunTaskIds.size > 0;

      const res = await window.PladazBridge.resumeQueue();
      if (reportCommandError(res, "Failed to resume download queue.")) {
        return;
      }
      state.sdAlert = null;
      syncQueueFlagsFromPayload(res);
      renderGlobalAlerts();
      renderQueueList();
    });

    document.getElementById("cancel-active-btn").addEventListener("click", () => {
      const active = state.queue.find((t) => t.status === "Downloading");
      if (active) openCancelConfirmModal(active.task_id);
    });

    document.getElementById("clear-completed-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.clearCompletedTasks();
      reportCommandError(res, "Failed to clear completed tasks.");
    });

    // Delegated clicks inside Queue List & Global Alerts & Storage
    document.body.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      const action = btn.getAttribute("data-action");
      const taskId = btn.getAttribute("data-task-id");

      if (action === "open-stages" && taskId) {
        openStageModal(taskId);
      } else if (action === "open-track" && taskId) {
        openTrackDetailView(taskId);
      } else if (action === "remove-or-cancel" && taskId) {
        const t = state.queue.find((x) => x.task_id === taskId);
        if (!t) return;
        if (t.status === "Downloading") {
          openCancelConfirmModal(taskId);
        } else {
          const res = await window.PladazBridge.removeTask(taskId);
          reportCommandError(res, "Failed to remove task from queue.");
        }
      } else if (action === "retry-task" && taskId) {
        const res = await window.PladazBridge.retryTask(taskId);
        reportCommandError(res, "Failed to retry task.");
      } else if (action === "summary-retry" && taskId) {
        const res = await window.PladazBridge.retryTask(taskId);
        if (!reportCommandError(res, "Failed to retry task.")) {
          closeModal("modal-queue-summary");
        }
      } else if (action === "view-task-error" && taskId) {
        const t = state.queue.find((x) => x.task_id === taskId);
        openErrorLogModal(t ? t.error : null);
      } else if (action === "quick-choose-folder") {
        const res = await window.PladazBridge.browseDestinationFolder();
        if (res && res.success) {
          state.config = res.config || state.config;
          state.sdStatus = res.sd_status || state.sdStatus;
          renderStorageGateBanner();
          renderSdCardWidget();
          renderQueueList();
        } else {
          reportCommandError(res, "Could not select destination folder.");
        }
      } else if (action === "select-drive-root") {
        const driveRoot = btn.getAttribute("data-drive-root");
        if (driveRoot) {
          const res = await window.PladazBridge.selectDetectedDrive(driveRoot);
          if (res && res.success) {
            state.config = res.config || state.config;
            state.sdStatus = res.sd_status || state.sdStatus;
            renderStorageGateBanner();
            renderSdCardWidget();
            renderStorageView();
            renderQueueList();
          } else {
            reportCommandError(res, "Selected drive is not connected or writable.");
          }
        }
      } else if (action === "alert-resume-queue") {
        state.queue
          .filter((t) => t.status === "Queued" || t.status === "Downloading")
          .forEach((t) => state.activeRunTaskIds.add(t.task_id));
        state.hadActiveRun = state.activeRunTaskIds.size > 0;
        const res = await window.PladazBridge.resumeQueue();
        if (!reportCommandError(res, "Failed to resume queue.")) {
          state.sdAlert = null;
          syncQueueFlagsFromPayload(res);
          renderGlobalAlerts();
          renderQueueList();
        }
      } else if (action === "dismiss-sd-alert") {
        state.sdAlert = null;
        renderGlobalAlerts();
      } else if (action === "dismiss-sys-alert") {
        state.systemAlert = null;
        renderGlobalAlerts();
      } else if (action === "dismiss-fetch-feedback") {
        document.getElementById("fetching-feedback-area").classList.add("hidden");
      } else if (action === "open-error-log") {
        openErrorLogModal(state.systemAlert);
      } else if (action === "reopen-conflict") {
        const conflict = state.pendingConflict || reconstructConflictFromQueue();
        if (conflict) {
          openConflictModal(conflict);
        }
      }
    });

    // Storage Widget & View buttons
    document.getElementById("widget-scan-sd-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.scanStorageDevices();
      if (res && res.success) {
        state.removableDrives = res.devices || [];
        state.sdStatus = res.sd_status || state.sdStatus;
        renderStorageGateBanner();
        renderSdCardWidget();
        renderQueueList();
      } else {
        reportCommandError(res, "Failed to scan storage devices.");
      }
    });
    document.getElementById("widget-open-storage-btn").addEventListener("click", () => switchView("storage"));
    document.getElementById("storage-scan-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.scanStorageDevices();
      if (res && res.success) {
        state.removableDrives = res.devices || [];
        state.sdStatus = res.sd_status || state.sdStatus;
        renderStorageView();
        renderSdCardWidget();
        renderStorageGateBanner();
      } else {
        reportCommandError(res, "Failed to scan storage devices.");
      }
    });
    document.getElementById("storage-choose-folder-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.browseDestinationFolder();
      if (res && res.success) {
        state.config = res.config || state.config;
        state.sdStatus = res.sd_status || state.sdStatus;
        renderStorageView();
        renderSdCardWidget();
        renderStorageGateBanner();
        renderQueueList();
      } else {
        reportCommandError(res, "Could not select destination folder.");
      }
    });

    // Settings View controls (Board 06)
    const settingsStatusEl = document.getElementById("settings-save-status");
    const setCoverLabel = (on) => {
      document.getElementById("settings-require-cover-label").textContent = on
        ? "ON (STRICT — FAIL IF MISSING)"
        : "OFF (WARN ONLY)";
    };
    // Save one setting right away; on failure show the backend error and put the control back (UX-06)
    async function autoSaveSetting(partial, revert) {
      settingsStatusEl.textContent = "SAVING…";
      const res = await window.PladazBridge.updateConfig(partial);
      if (res && res.success) {
        state.config = res.config || Object.assign({}, state.config, partial);
        settingsStatusEl.textContent = "✓ SAVED TO CONFIG.JSON";
        return true;
      }
      const msg = (res && res.error && res.error.message_en) || "Setting was not saved.";
      settingsStatusEl.textContent = `✕ NOT SAVED — ${msg}`;
      reportCommandError(res, "Failed to save settings to config.json.");
      revert();
      return false;
    }
    document.getElementById("settings-require-cover-checkbox").addEventListener("change", (e) => {
      const on = Boolean(e.target.checked);
      setCoverLabel(on);
      autoSaveSetting({ require_album_art: on }, () => {
        const saved = Boolean(state.config.require_album_art);
        e.target.checked = saved;
        setCoverLabel(saved);
      });
    });
    document.getElementById("settings-mb-ua-input").addEventListener("change", (e) => {
      const value = String(e.target.value || "").trim();
      if (value === (state.config.musicbrainz_user_agent || "")) return;
      autoSaveSetting({ musicbrainz_user_agent: value }, () => {
        e.target.value = state.config.musicbrainz_user_agent || "";
      });
    });
    document.getElementById("settings-browse-dest-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.browseDestinationFolder();
      if (res && res.success) {
        state.config = res.config || state.config;
        state.sdStatus = res.sd_status || state.sdStatus;
        document.getElementById("settings-dest-input").value = state.config.destination_path || "";
        renderStorageGateBanner();
        renderSdCardWidget();
      } else {
        reportCommandError(res, "Could not select destination folder.");
      }
    });
    document.getElementById("settings-choose-cookies-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.selectCookiesFile();
      if (res && res.success) {
        state.config.cookies_file_path = res.selected_path;
        document.getElementById("settings-cookies-filename").textContent = res.filename || "Not selected";
      } else {
        reportCommandError(res, "Could not select cookies.txt file.");
      }
    });
    document.getElementById("settings-remove-cookies-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.clearCookiesFile();
      if (res && res.success) {
        state.config.cookies_file_path = null;
        document.getElementById("settings-cookies-filename").textContent = "Not selected";
      } else {
        reportCommandError(res, "Could not clear cookies.txt configuration.");
      }
    });

    // Browser Authentication controls (Option C)
    const bSelect = document.getElementById("settings-browser-select");
    if (bSelect) {
      bSelect.addEventListener("change", () => {
        const recTag = document.getElementById("settings-browser-recommended-tag");
        const recKey = state.browserDetection ? state.browserDetection.recommended : null;
        if (recTag) {
          if (bSelect.value && bSelect.value === recKey) {
            recTag.classList.remove("hidden");
          } else {
            recTag.classList.add("hidden");
          }
        }
      });
    }

    const useBrowserBtn = document.getElementById("settings-use-browser-btn");
    if (useBrowserBtn) {
      useBrowserBtn.addEventListener("click", () => {
        const sel = document.getElementById("settings-browser-select");
        const chosen = sel ? sel.value : "";
        if (!chosen) return;
        openBrowserConsentModal(chosen);
      });
    }

    const consentCancelBtn = document.getElementById("browser-consent-cancel-btn");
    if (consentCancelBtn) {
      consentCancelBtn.addEventListener("click", closeBrowserConsentModal);
    }

    const consentContinueBtn = document.getElementById("browser-consent-continue-btn");
    if (consentContinueBtn) {
      consentContinueBtn.addEventListener("click", async () => {
        const chosen = state.pendingConsentBrowser;
        closeBrowserConsentModal();
        if (!chosen) return;

        setBrowserFeedback("Verifying browser cookies with yt-dlp…", "PLADAZ is checking if cookies can be read without downloading.");
        const res = await window.PladazBridge.selectBrowserCookies(chosen);
        if (res && res.success) {
          state.browserCookies = {
            enabled: true,
            browser: res.browser,
            browser_label: res.browser_label,
          };
          if (res.config) state.config = res.config;
          const checkMsg = res.check ? res.check.message : "Cookies verified successfully.";
          const checkStep = res.check ? res.check.next_step : "";
          setBrowserFeedback(`✓ ${checkMsg}`, checkStep, false);
        } else {
          state.browserCookies = {
            enabled: false,
            browser: res.browser || chosen,
            browser_label: res.browser_label || chosen,
          };
          if (res && res.config) state.config = res.config;
          const errMsg = (res && res.check && res.check.message) || (res && res.error && res.error.message_en) || "Could not read cookies from selected browser.";
          const nextStep = (res && res.check && res.check.next_step) || "Try closing the browser or choose another supported browser.";
          setBrowserFeedback(`! ${errMsg}`, nextStep, true);
        }
        renderBrowserAuthSection();
      });
    }

    const testBrowserBtn = document.getElementById("settings-test-browser-btn");
    if (testBrowserBtn) {
      testBrowserBtn.addEventListener("click", async () => {
        const sel = document.getElementById("settings-browser-select");
        const chosen = sel ? sel.value : (state.browserCookies && state.browserCookies.browser);
        if (!chosen) return;

        setBrowserFeedback(`Testing cookies from ${chosen}…`, "Testing reading cookie count via yt-dlp.");
        const res = await window.PladazBridge.testBrowserCookies(chosen);
        if (res && res.success) {
          const checkMsg = res.check ? res.check.message : "Cookies can be read.";
          const checkStep = res.check ? res.check.next_step : "";
          setBrowserFeedback(`✓ ${checkMsg}`, checkStep, false);
        } else {
          const errMsg = (res && res.check && res.check.message) || (res && res.error && res.error.message_en) || "Cookie test failed.";
          const nextStep = (res && res.check && res.check.next_step) || "Check guidance or try another browser.";
          setBrowserFeedback(`! ${errMsg}`, nextStep, true);
        }
      });
    }

    const removeBrowserBtn = document.getElementById("settings-remove-browser-btn");
    if (removeBrowserBtn) {
      removeBrowserBtn.addEventListener("click", async () => {
        const res = await window.PladazBridge.clearBrowserCookies();
        if (res && res.success) {
          state.browserCookies = { enabled: false, browser: null, browser_label: null };
          if (res.config) state.config = res.config;
          setBrowserFeedback("Browser Authentication disabled.", "Downloads will not use browser cookies unless configured again.", false);
          renderBrowserAuthSection();
        } else {
          reportCommandError(res, "Could not disable browser authentication.");
        }
      });
    }
    document.getElementById("settings-open-updater-btn").addEventListener("click", () => {
      document.getElementById("updater-current-ver").textContent =
        (state.ytdlpStatus && state.ytdlpStatus.version) || "Not installed";
      document.getElementById("updater-new-ver").textContent = "—";
      openModal("modal-updater");
    });
    document.getElementById("settings-open-about-btn").addEventListener("click", openAboutModal);

    // History View controls (Board 07)
    document.querySelectorAll(".hist-filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.historyFilter = btn.getAttribute("data-hist-filter") || "all";
        document.querySelectorAll(".hist-filter-btn").forEach((b) => {
          b.classList.toggle("hot", b === btn);
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        renderHistoryList();
      });
    });
    document.getElementById("history-clear-btn").addEventListener("click", () => {
      const count = state.historyEntries.length;
      document.getElementById("clear-history-count").textContent =
        count === 1 ? "1 record" : `${count} records`;
      openModal("modal-clear-history");
      document.getElementById("clear-history-no-btn").focus();
    });
    document.getElementById("clear-history-no-btn").addEventListener("click", () => {
      closeModal("modal-clear-history");
    });
    document.getElementById("clear-history-yes-btn").addEventListener("click", async () => {
      closeModal("modal-clear-history");
      const res = await window.PladazBridge.clearHistory();
      if (res && res.success) {
        state.historyEntries = [];
        renderHistoryList();
      } else {
        reportCommandError(res, "Failed to clear history.");
      }
    });

    // Board 04: Disclaimer Modal
    const discCb = document.getElementById("disclaimer-accept-checkbox");
    const discAcceptBtn = document.getElementById("disclaimer-accept-btn");
    const syncDisclaimerBtn = () => {
      discAcceptBtn.disabled = !discCb.checked;
    };
    discCb.addEventListener("change", syncDisclaimerBtn);
    discCb.addEventListener("input", syncDisclaimerBtn);
    discAcceptBtn.addEventListener("click", async () => {
      if (!discCb.checked) return;
      discAcceptBtn.disabled = true;
      const res = await window.PladazBridge.acceptDisclaimer();
      discAcceptBtn.disabled = false;
      if (res && res.success) {
        state.config.disclaimer_accepted = true;
        closeModal("modal-disclaimer");
        if (!state.ytdlpStatus || !state.ytdlpStatus.present) {
          openYtdlpSetupModal();
        } else if (state.pendingConflict) {
          openConflictModal(state.pendingConflict);
        }
      } else {
        reportCommandError(res, "Failed to save disclaimer acceptance.");
      }
    });
    document.getElementById("disclaimer-quit-btn").addEventListener("click", () => {
      window.PladazBridge.quitApp();
    });
    document.getElementById("disclaimer-close-readonly-btn").addEventListener("click", () => {
      closeModal("modal-disclaimer");
    });

    // Board 09: yt-dlp Setup Modal
    document.getElementById("setup-download-btn").addEventListener("click", async () => {
      const statusBox = document.getElementById("setup-status-box");
      const dlBtn = document.getElementById("setup-download-btn");
      dlBtn.disabled = true;
      statusBox.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--soft)] text-[var(--ink)] p-3 text-xs font-medium";
      statusBox.textContent = "Downloading standalone yt-dlp.exe from official GitHub release…";
      const res = await window.PladazBridge.updateYtdlpModule();
      dlBtn.disabled = false;
      if (res && res.success) {
        state.ytdlpStatus.present = true;
        state.ytdlpStatus.version = res.new_version;
        statusBox.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] p-3 text-xs font-bold";
        statusBox.textContent = `✓ yt-dlp.exe (${res.new_version}) installed and verified!`;
        document.getElementById("setup-open-app-btn").classList.remove("hidden");
        populateSettingsForm();
      } else {
        statusBox.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] p-3 text-xs font-bold";
        statusBox.textContent = (res && res.message) || (res && res.error && res.error.message_en) || "Failed to download yt-dlp.exe.";
      }
    });
    document.getElementById("setup-locate-btn").addEventListener("click", async () => {
      const statusBox = document.getElementById("setup-status-box");
      const res = await window.PladazBridge.locateYtdlpFile();
      if (res && res.success && res.present) {
        state.ytdlpStatus = res;
        populateSettingsForm();
        closeModal("modal-ytdlp-setup");
        if (state.pendingConflict) {
          openConflictModal(state.pendingConflict);
        }
      } else if (res && !res.cancelled && res.error) {
        statusBox.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] p-3 text-xs font-bold";
        statusBox.textContent = res.error.message_en || "Invalid yt-dlp.exe file selected.";
      }
    });
    document.getElementById("setup-recheck-btn").addEventListener("click", async () => {
      const statusBox = document.getElementById("setup-status-box");
      const res = await window.PladazBridge.checkYtdlpStatus();
      if (res && res.success && res.present) {
        state.ytdlpStatus = res;
        populateSettingsForm();
        closeModal("modal-ytdlp-setup");
        if (state.pendingConflict) {
          openConflictModal(state.pendingConflict);
        }
      } else {
        statusBox.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--warn)] text-[var(--warn-ink)] p-3 text-xs font-bold";
        statusBox.textContent = "Still not found at the expected location. Click DOWNLOAD YT-DLP or LOCATE FILE…";
      }
    });
    document.getElementById("setup-open-app-btn").addEventListener("click", () => {
      closeModal("modal-ytdlp-setup");
      if (state.pendingConflict) {
        openConflictModal(state.pendingConflict);
      }
    });

    // Board 05: Conflict Prompt Modal (Keep pendingConflict and modal open until resolveConflict succeeds)
    async function submitConflictChoice(action) {
      const conflict = state.pendingConflict || reconstructConflictFromQueue();
      if (!conflict || !conflict.task_id) return;
      const scopeEl = document.querySelector('input[name="conflict-scope"]:checked');
      const scope = scopeEl ? scopeEl.value : "single";
      const btns = [
        document.getElementById("conflict-skip-btn"),
        document.getElementById("conflict-keep-both-btn"),
        document.getElementById("conflict-overwrite-btn"),
      ];
      btns.forEach((b) => {
        if (b) b.disabled = true;
      });
      const res = await window.PladazBridge.resolveConflict(conflict.task_id, action, scope);
      btns.forEach((b) => {
        if (b) b.disabled = false;
      });

      if (res && res.success) {
        state.pendingConflict = null;
        closeModal("modal-conflict");
      } else {
        reportCommandError(res, "Failed to resolve duplicate file conflict.");
      }
    }
    document.getElementById("conflict-skip-btn").addEventListener("click", () => submitConflictChoice("skip"));
    document.getElementById("conflict-keep-both-btn").addEventListener("click", () => submitConflictChoice("keep_both"));
    document.getElementById("conflict-overwrite-btn").addEventListener("click", () => submitConflictChoice("overwrite"));

    // Board 11: Cancel Confirm Modal (Wait for Backend response instead of mutating queueHalted prematurely)
    document.getElementById("cancel-confirm-no-btn").addEventListener("click", () => {
      state.pendingCancelTaskId = null;
      closeModal("modal-cancel-confirm");
    });
    document.getElementById("cancel-confirm-yes-btn").addEventListener("click", async () => {
      const taskId = state.pendingCancelTaskId;
      state.pendingCancelTaskId = null;
      closeModal("modal-cancel-confirm");
      if (taskId) {
        const res = await window.PladazBridge.cancelTask(taskId);
        if (!reportCommandError(res, "Failed to cancel task.")) {
          syncQueueFlagsFromPayload(res);
          renderQueueList();
        }
      }
    });

    // Board 14: Stage Modal close
    document.getElementById("task-stages-close-btn").addEventListener("click", () => {
      closeModal("modal-task-stages");
    });

    // Board 15: Summary Modal buttons
    document.getElementById("summary-view-history-btn").addEventListener("click", () => {
      closeModal("modal-queue-summary");
      switchView("history");
    });
    document.getElementById("summary-open-folder-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.openFolder("destination");
      reportCommandError(res, "Could not open destination folder on Micro SD Card.");
    });
    document.getElementById("summary-done-btn").addEventListener("click", () => {
      closeModal("modal-queue-summary");
    });

    // Board 16: Updater Modal
    document.getElementById("updater-run-btn").addEventListener("click", async () => {
      const runBtn = document.getElementById("updater-run-btn");
      const msgEl = document.getElementById("updater-status-msg");
      state.ytdlpUpdating = true;
      setUpdaterCloseLocked(true);
      renderQueueList();
      runBtn.disabled = true;
      runBtn.textContent = "UPDATING…";
      msgEl.textContent = "Downloading and verifying latest yt-dlp.exe… (Start Queue is paused during update)";

      const res = await window.PladazBridge.updateYtdlpModule();
      state.ytdlpUpdating = false;
      setUpdaterCloseLocked(false);
      runBtn.disabled = false;
      runBtn.textContent = "UPDATE NOW";
      renderQueueList();

      if (res && res.success) {
        state.ytdlpStatus.present = true;
        state.ytdlpStatus.version = res.new_version;
        document.getElementById("updater-new-ver").textContent = res.new_version || "Latest";
        msgEl.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--mint)] text-[var(--mint-ink)] p-3 text-xs font-bold";
        msgEl.textContent = res.message || "Updated successfully!";
        populateSettingsForm();
      } else {
        msgEl.className = "rounded-xl border-2 border-[var(--ink)] bg-[var(--err)] text-[var(--err-ink)] p-3 text-xs font-bold";
        msgEl.textContent = (res && res.message) || "Update failed; previous version kept intact.";
      }
    });
    document.getElementById("updater-close-btn").addEventListener("click", () => {
      if (state.ytdlpUpdating) return;
      closeModal("modal-updater");
    });
    document.getElementById("updater-done-btn").addEventListener("click", () => {
      if (state.ytdlpUpdating) return;
      closeModal("modal-updater");
    });

    // Board 17: Error Log Modal
    document.getElementById("error-log-copy-btn").addEventListener("click", () => {
      const text = document.getElementById("error-log-terminal").innerText || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
      }
    });
    document.getElementById("error-log-open-folder-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.openFolder("logs");
      reportCommandError(res, "Could not open logs folder.");
    });
    document.getElementById("error-log-close-btn").addEventListener("click", () => {
      closeModal("modal-error-log");
    });
    document.getElementById("error-log-done-btn").addEventListener("click", () => {
      closeModal("modal-error-log");
    });

    // Board 20: About Modal
    document.getElementById("about-open-disclaimer-btn").addEventListener("click", () => {
      closeModal("modal-about");
      openDisclaimerModal(true);
    });
    document.getElementById("about-toggle-notices-btn").addEventListener("click", () => {
      document.getElementById("about-notices-panel").classList.toggle("hidden");
    });
    document.getElementById("about-open-logs-btn").addEventListener("click", async () => {
      const res = await window.PladazBridge.openFolder("logs");
      reportCommandError(res, "Could not open logs folder.");
    });
    document.getElementById("about-close-btn").addEventListener("click", () => {
      closeModal("modal-about");
    });
    document.getElementById("about-back-btn").addEventListener("click", () => {
      closeModal("modal-about");
    });

    document.addEventListener("keydown", trapFocusInOpenModal);

    // Keyboard Esc handling (Closes dismissible modals; NEVER closes Board 05 Conflict Prompt or Board 04 mandatory first-launch disclaimer)
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!document.getElementById("modal-cancel-confirm").classList.contains("hidden")) {
        state.pendingCancelTaskId = null;
        closeModal("modal-cancel-confirm");
        return;
      }
      if (!document.getElementById("modal-clear-history").classList.contains("hidden")) {
        closeModal("modal-clear-history");
        return;
      }
      if (!document.getElementById("modal-browser-consent").classList.contains("hidden")) {
        closeBrowserConsentModal();
        return;
      }
      const dismissible = ["modal-task-stages", "modal-queue-summary", "modal-error-log", "modal-about"];
      if (!state.ytdlpUpdating) dismissible.push("modal-updater");
      dismissible.forEach((id) => {
        const el = document.getElementById(id);
        if (el && !el.classList.contains("hidden")) {
          closeModal(id);
        }
      });
    });
  }

  // =========================================================================
  // BRIDGE SUBSCRIPTIONS (6 Events from Python Core)
  // =========================================================================
  function subscribeBridgeEvents() {
    window.PladazBridge.on("queue:updated", (data) => {
      state.queue = (data && data.tasks) || [];
      syncQueueFlagsFromPayload(data);
      renderQueueList();
      renderNowProcessing();
      if (state.currentView === "track") renderTrackDetailView();
      if (!document.getElementById("modal-task-stages").classList.contains("hidden")) renderStageModal();
      checkAndShowQueueSummary();
    });

    window.PladazBridge.on("task:progress", (data) => {
      if (!data || !data.task_id) return;
      const t = state.queue.find((x) => x.task_id === data.task_id);
      if (t) {
        t.stage = data.stage;
        t.progress_percent = data.progress_percent;
        if (data.speed_str || data.eta_str) {
          t._speedEta = `Speed: ${data.speed_str || "—"} · ETA: ${data.eta_str || "—"}`;
        }
        updateTaskRowProgress(t);
      }
      renderNowProcessing();
      if (!document.getElementById("modal-task-stages").classList.contains("hidden")) renderStageModal();
    });

    window.PladazBridge.on("task:status_changed", (data) => {
      if (!data || !data.task) return;
      syncQueueFlagsFromPayload(data);
      const updated = data.task;
      if (state.hadActiveRun && updated.status === "Downloading") {
        state.activeRunTaskIds.add(updated.task_id);
      }
      const idx = state.queue.findIndex((x) => x.task_id === updated.task_id);
      if (idx >= 0) {
        state.queue[idx] = updated;
      } else {
        state.queue.push(updated);
      }
      if (updated.has_cover) {
        ensureCoverLoaded(updated.task_id);
      }
      if (updated.status === "Completed" || updated.status === "Failed") {
        const name = getTaskDisplayTitle(updated);
        announce(updated.status === "Completed"
          ? `${name}: completed.`
          : `${name}: failed${updated.error ? `, ${updated.error.code}` : ""}.`);
      }
      renderQueueList();
      renderNowProcessing();
      if (state.currentView === "track" && state.selectedTrackId === updated.task_id) {
        renderTrackDetailView();
      }
      if (!document.getElementById("modal-task-stages").classList.contains("hidden")) renderStageModal();
      checkAndShowQueueSummary();
    });

    window.PladazBridge.on("task:conflict_prompt", (data) => {
      if (!data || !data.task_id) return;
      openConflictModal(data);
    });

    window.PladazBridge.on("sdcard:status_changed", (data) => {
      if (data && data.status) {
        state.sdStatus = data.status;
      }
      if (data && data.alert) {
        state.sdAlert = data.alert;
        state.queueHalted = true;
      }
      renderGlobalAlerts();
      renderStorageGateBanner();
      renderSdCardWidget();
      renderStorageView();
      renderQueueList();
    });

    window.PladazBridge.on("system:error", (data) => {
      if (data && data.error) {
        state.systemAlert = data.error;
        renderGlobalAlerts();
      }
    });
  }

  // =========================================================================
  // INITIALIZATION
  // =========================================================================
  async function initApp() {
    bindEvents();
    subscribeBridgeEvents();

    const initRes = await window.PladazBridge.getInitialState();
    if (initRes && initRes.success) {
      state.version = initRes.version || "1.0.0";
      state.config = initRes.config || state.config;
      state.sdStatus = initRes.sd_status || null;
      state.removableDrives = initRes.removable_drives || [];
      state.queue = initRes.queue || [];
      state.queueRunning = Boolean(initRes.queue_running);
      state.queueHalted = Boolean(initRes.queue_halted);
      state.ytdlpStatus = initRes.ytdlp_status || state.ytdlpStatus;
      state.systemInfo = initRes.system_info || {};
      state.browserDetection = initRes.browser_detection || null;
      state.browserCookies = initRes.browser_cookies || {
        enabled: Boolean(state.config.browser_cookies_enabled),
        browser: state.config.browser_cookies_name || null,
        browser_label: null,
      };
      if (initRes.startup_error) {
        state.systemAlert = initRes.startup_error;
      }
      const initialConflict = initRes.pending_conflict || reconstructConflictFromQueue();
      if (initialConflict) {
        state.pendingConflict = initialConflict;
      }
      if (state.queueRunning) {
        state.hadActiveRun = true;
        state.queue
          .filter((t) => t.status === "Queued" || t.status === "Downloading")
          .forEach((t) => state.activeRunTaskIds.add(t.task_id));
      }
    } else {
      reportCommandError(initRes, "Failed to load initial application state.");
    }

    renderGlobalAlerts();
    renderStorageGateBanner();
    renderQueueList();
    renderNowProcessing();
    renderSdCardWidget();

    // Startup Gate 1: First-Launch Personal Use Disclaimer (Board 04)
    if (!state.config.disclaimer_accepted) {
      openDisclaimerModal(false);
    } else if (!state.ytdlpStatus || !state.ytdlpStatus.present) {
      // Startup Gate 2: Standalone yt-dlp.exe Missing (Board 09)
      openYtdlpSetupModal();
    } else if (state.pendingConflict) {
      // Restore pending duplicate file conflict prompt if a task was waiting on conflict
      openConflictModal(state.pendingConflict);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
})();
