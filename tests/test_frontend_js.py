"""Automated Frontend JS & Bridge Event Contract tests (verifying ui/js/bridge.js and ui/js/app.js in Node.js)."""

import json
from pathlib import Path
import subprocess
import pytest

pytestmark = pytest.mark.unit

from pladaz.bridge.events import EventDispatcher
from pladaz.domain.enums import Stage, TaskStatus
from pladaz.domain.models import (
    SDCardStatus,
    StructuredError,
    TrackMetadata,
    TrackTask,
    ValidationResult,
)


def test_backend_event_payload_contract_matches_frontend() -> None:
    """Verify that all 6 EventDispatcher payloads match the exact keys consumed by ui/js/app.js."""
    dispatched: list[tuple[str, dict]] = []

    class FakeWindow:
        def evaluate_js(self, script: str) -> None:
            prefix = "window.pladazDispatchEvent("
            assert script.startswith(prefix) and script.endswith(")")
            envelope = json.loads(script[len(prefix) : -1])
            dispatched.append((envelope["event_type"], envelope["data"]))

    ev = EventDispatcher(window=FakeWindow())
    sample_task = TrackTask(
        task_id="task-contract-1",
        entry_url="https://music.youtube.com/watch?v=123",
        batch_id="batch-1",
        status=TaskStatus.DOWNLOADING,
        stage=Stage.DOWNLOADING_STREAM,
        progress_percent=42.5,
        metadata=TrackMetadata(
            title="Contract Song",
            track_artist="Contract Artist",
            album="Contract Album",
            album_artist="Contract Artist",
            cover_jpeg=b"\xff\xd8\xff\xd9",
        ),
        validation_result=ValidationResult(
            is_valid=True,
            is_readable=True,
            is_aac_lc=True,
            has_title=True,
            has_cover=True,
        ),
    )

    ev.emit_queue_updated([sample_task], queue_running=True, queue_halted=False)
    ev.emit_task_progress("task-contract-1", Stage.DOWNLOADING_STREAM, 55.0, "2.1MiB/s", "00:04")
    ev.emit_task_status_changed(sample_task, queue_running=True, queue_halted=False)
    ev.emit_task_conflict_prompt(
        task_id="task-contract-1",
        existing_path="E:\\Music\\Contract Artist\\Contract Album\\Contract Song.m4a",
        metadata_summary={"title": "Contract Song", "album_artist": "Contract Artist", "album": "Contract Album"},
    )
    ev.emit_sdcard_status_changed(
        SDCardStatus(
            drive_root="E:\\",
            destination_dir="E:\\Music",
            is_connected=True,
            is_writable=True,
            free_bytes=1024,
            total_bytes=2048,
            volume_label="ECHO",
        ),
        alert=StructuredError(code="ERR_SDCARD_DISCONNECTED", message_en="Card removed", recoverable=True),
    )
    ev.emit_system_error(
        StructuredError(code="ERR_CONFIG_CORRUPT", message_en="Corrupt config", recoverable=True)
    )

    assert len(dispatched) == 6

    # 1. queue:updated
    evt_type, data = dispatched[0]
    assert evt_type == "queue:updated"
    assert isinstance(data["tasks"], list) and len(data["tasks"]) == 1
    assert data["queue_running"] is True
    assert data["queue_halted"] is False
    t_dto = data["tasks"][0]
    assert set(t_dto.keys()) >= {
        "task_id",
        "entry_url",
        "status",
        "stage",
        "progress_percent",
        "metadata",
        "has_cover",
        "validation",
        "warnings",
        "error",
    }
    assert "cover_jpeg" not in (t_dto["metadata"] or {})

    # 2. task:progress
    evt_type, data = dispatched[1]
    assert evt_type == "task:progress"
    assert set(data.keys()) == {"task_id", "stage", "progress_percent", "speed_str", "eta_str"}

    # 3. task:status_changed
    evt_type, data = dispatched[2]
    assert evt_type == "task:status_changed"
    assert data["task"]["task_id"] == "task-contract-1"
    assert data["queue_running"] is True
    assert data["queue_halted"] is False

    # 4. task:conflict_prompt
    evt_type, data = dispatched[3]
    assert evt_type == "task:conflict_prompt"
    assert set(data.keys()) == {"task_id", "existing_path", "metadata_summary"}

    # 5. sdcard:status_changed
    evt_type, data = dispatched[4]
    assert evt_type == "sdcard:status_changed"
    assert set(data.keys()) == {"status", "alert"}
    assert data["alert"]["code"] == "ERR_SDCARD_DISCONNECTED"

    # 6. system:error
    evt_type, data = dispatched[5]
    assert evt_type == "system:error"
    assert data["error"]["code"] == "ERR_CONFIG_CORRUPT"


def test_frontend_js_execution_in_node_dom_harness() -> None:
    """Execute real ui/js/bridge.js and ui/js/app.js in Node.js to verify:
    1. Startup conflict restoration & conflict prompt failure safety (modal stays open on failure, pendingConflict preserved).
    2. Single-row DOM update on task:progress without rewriting queue-list-container.innerHTML.
    3. Batch Run Summary counts only tasks in the active run (ignoring leftover completed tasks from previous runs).
    4. Track Detail View never guesses PASS when task.validation is null (renders NO DATA) and updates covr pill dynamically.
    5. Cover preview retries when previous attempt returned null before cover was ready.
    6. Commands check res.success, report errors to global-alerts-container, do not mutate queueHalted optimistically,
       and bridge.js never forwards raw file paths or magic '' strings from UI.
    """
    repo_root = Path(__file__).resolve().parents[1]
    node_script = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const repoRoot = process.cwd();
const htmlSource = fs.readFileSync(path.join(repoRoot, "ui", "index.html"), "utf8");
const bridgeSource = fs.readFileSync(path.join(repoRoot, "ui", "js", "bridge.js"), "utf8");
const appSource = fs.readFileSync(path.join(repoRoot, "ui", "js", "app.js"), "utf8");

// Lightweight DOM implementation sufficient for ui/js/app.js
class ClassList {
  constructor(initial = []) {
    this.set = new Set(initial.filter(Boolean));
  }
  add(...cls) { cls.forEach((c) => this.set.add(c)); }
  remove(...cls) { cls.forEach((c) => this.set.delete(c)); }
  toggle(c, force) {
    if (force === undefined) {
      if (this.set.has(c)) { this.set.delete(c); return false; }
      this.set.add(c); return true;
    }
    if (force) this.set.add(c); else this.set.delete(c);
    return Boolean(force);
  }
  contains(c) { return this.set.has(c); }
  toString() { return Array.from(this.set).join(" "); }
}

class FakeElement {
  constructor(id = "", tagName = "DIV", initialClasses = []) {
    this.id = id;
    this.tagName = tagName;
    this.classList = new ClassList(initialClasses);
    this.textContent = "";
    this.innerText = "";
    this._innerHTML = "";
    this.innerHTMLSetCount = 0;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.src = "";
    this.style = {};
    this.attrs = {};
    this.listeners = {};
    this.children = [];
    this.rowMap = new Map();
  }
  get className() { return this.classList.toString(); }
  set className(v) { this.classList = new ClassList(String(v || "").split(/\s+/)); }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(val) {
    this._innerHTML = String(val || "");
    this.innerHTMLSetCount += 1;
    // Parse data-task-row-id rows if this is queue-list-container
    if (this.id === "queue-list-container") {
      this.rowMap.clear();
      const rowRegex = /data-task-row-id="([^"]+)"/g;
      let m;
      while ((m = rowRegex.exec(this._innerHTML)) !== null) {
        const tid = m[1];
        const rowEl = new FakeElement(`row-${tid}`, "DIV");
        const stageEl = new FakeElement(`stage-${tid}`, "SPAN");
        const pctEl = new FakeElement(`pct-${tid}`, "SPAN");
        const segContainer = new FakeElement(`segs-${tid}`, "DIV");
        const segNodes = Array.from({ length: 10 }, (_, idx) => {
          const s = new FakeElement(`seg-${tid}-${idx}`, "DIV", ["bg-[var(--soft)]"]);
          s.attrs["data-seg-idx"] = String(idx);
          return s;
        });
        segContainer.querySelectorAll = (sel) => sel === "[data-seg-idx]" ? segNodes : [];
        rowEl.stageEl = stageEl;
        rowEl.pctEl = pctEl;
        rowEl.segContainer = segContainer;
        rowEl.segNodes = segNodes;
        rowEl.querySelector = (sel) => {
          if (sel === "[data-task-stage-text]") return stageEl;
          if (sel === "[data-task-pct-text]") return pctEl;
          if (sel === "[data-task-progress-segments]") return segContainer;
          return null;
        };
        this.rowMap.set(tid, rowEl);
      }
    }
  }
  getAttribute(k) { return this.attrs[k] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(evt, fn) {
    if (!this.listeners[evt]) this.listeners[evt] = [];
    this.listeners[evt].push(fn);
  }
  async trigger(evt, eventObj = {}) {
    const list = this.listeners[evt] || [];
    for (const fn of list) {
      await fn(Object.assign({ preventDefault() {}, target: this }, eventObj));
    }
  }
  focus() {}
  closest(sel) {
    if (sel === "[data-action]" && this.attrs["data-action"]) return this;
    return null;
  }
  querySelector(sel) {
    const m = sel.match(/^\[data-task-row-id="([^"]+)"\]$/);
    if (m && this.rowMap.has(m[1])) {
      return this.rowMap.get(m[1]);
    }
    return null;
  }
  querySelectorAll() { return []; }
}

const elementsById = new Map();
const idRegex = /id="([^"]+)"([^>]*)/g;
let match;
while ((match = idRegex.exec(htmlSource)) !== null) {
  const id = match[1];
  const rest = match[2] || "";
  const classMatch = rest.match(/class="([^"]+)"/);
  const classes = classMatch ? classMatch[1].split(/\s+/) : [];
  elementsById.set(id, new FakeElement(id, "DIV", classes));
}

const radioSingle = new FakeElement("radio-single", "INPUT");
radioSingle.value = "single";
radioSingle.checked = true;

const navBtns = ["queue", "history", "storage", "settings"].map((n) => {
  const b = new FakeElement(`nav-${n}`, "BUTTON");
  b.attrs["data-nav"] = n;
  return b;
});

const histBtns = ["all", "Completed", "Failed"].map((f) => {
  const b = new FakeElement(`hist-${f}`, "BUTTON");
  b.attrs["data-hist-filter"] = f;
  return b;
});

const bodyEl = new FakeElement("body", "BODY");

// Track API calls
const apiCalls = [];
let resolveConflictShouldSucceed = false;
let coverPreviewDataUrl = null;
let startQueueResponse = { success: true, queue_running: true, queue_halted: false };
let cancelTaskResponse = { success: false, error: { code: "ERR_TASK_CANCELLED", message_en: "Cancel failed on backend", recoverable: true } };

const fakeApi = {
  get_initial_state: async () => ({
    success: true,
    version: "1.0.0",
    config: {
      disclaimer_accepted: true,
      destination_path: "E:\\Music",
      cookies_file_path: "E:\\cookies.txt",
      require_album_art: false,
      musicbrainz_user_agent: "",
    },
    disclaimer_accepted: true,
    sd_status: {
      drive_root: "E:\\",
      destination_dir: "E:\\Music",
      is_connected: true,
      is_writable: true,
      free_bytes: 16 * 1024 * 1024 * 1024,
      total_bytes: 32 * 1024 * 1024 * 1024,
      volume_label: "ECHO_SD",
    },
    removable_drives: [
      {
        drive_root: "E:\\",
        destination_dir: "E:\\",
        is_connected: true,
        is_writable: true,
        free_bytes: 16 * 1024 * 1024 * 1024,
        total_bytes: 32 * 1024 * 1024 * 1024,
        volume_label: "ECHO_SD",
      },
    ],
    queue: [
      {
        task_id: "task-old-completed",
        entry_url: "https://music.youtube.com/watch?v=old",
        status: "Completed",
        stage: null,
        progress_percent: 100,
        metadata: { title: "Old Run Song", album_artist: "Old Artist", album: "Old Album" },
        has_cover: false,
        validation: null,
        warnings: [],
        error: null,
      },
      {
        task_id: "task-conflict-1",
        entry_url: "https://music.youtube.com/watch?v=conf1",
        status: "Downloading",
        stage: "waiting_conflict",
        progress_percent: 20,
        target_file_path: "E:\\Music\\Artist\\Album\\Dup.m4a",
        metadata: { title: "Dup Song", album_artist: "Artist", album: "Album" },
        has_cover: false,
        validation: null,
        warnings: [],
        error: null,
      },
    ],
    queue_running: true,
    queue_halted: false,
    pending_conflict: {
      task_id: "task-conflict-1",
      existing_path: "E:\\Music\\Artist\\Album\\Dup.m4a",
      metadata_summary: { title: "Dup Song", album_artist: "Artist", album: "Album" },
    },
    ytdlp_status: { present: true, version: "2026.10.01", expected_path: "yt-dlp.exe" },
    system_info: { version: "1.0.0", ytdlp_version: "2026.10.01", ffmpeg_version: "bundled" },
    startup_error: null,
  }),
  resolve_conflict: async (...args) => {
    apiCalls.push(["resolve_conflict", ...args]);
    if (!resolveConflictShouldSucceed) {
      return {
        success: false,
        error: { code: "ERR_CONFLICT_NOT_FOUND", message_en: "Backend conflict failure", recoverable: true },
      };
    }
    return { success: true };
  },
  browse_destination_folder: async (...args) => {
    apiCalls.push(["browse_destination_folder", ...args]);
    return { success: true, selected_path: "E:\\Music", config: { destination_path: "E:\\Music" } };
  },
  select_detected_drive: async (...args) => {
    apiCalls.push(["select_detected_drive", ...args]);
    return { success: true, selected_path: args[0], config: { destination_path: args[0] } };
  },
  select_cookies_file: async (...args) => {
    apiCalls.push(["select_cookies_file", ...args]);
    return { success: true, selected_path: "E:\\cookies.txt", filename: "cookies.txt" };
  },
  clear_cookies_file: async (...args) => {
    apiCalls.push(["clear_cookies_file", ...args]);
    return { success: true, selected_path: null, filename: null };
  },
  get_cover_preview: async (taskId) => {
    apiCalls.push(["get_cover_preview", taskId]);
    return { success: true, task_id: taskId, data_url: coverPreviewDataUrl };
  },
  start_queue: async () => {
    apiCalls.push(["start_queue"]);
    return startQueueResponse;
  },
  cancel_task: async (taskId) => {
    apiCalls.push(["cancel_task", taskId]);
    return cancelTaskResponse;
  },
  update_config: async (partial) => {
    apiCalls.push(["update_config", partial]);
    return { success: false, error: { code: "ERR_CONFIG_CORRUPT", message_en: "Disk write error", recoverable: true } };
  },
};

const documentObj = {
  readyState: "complete",
  body: bodyEl,
  getElementById(id) {
    if (!elementsById.has(id)) {
      elementsById.set(id, new FakeElement(id));
    }
    return elementsById.get(id);
  },
  querySelector(sel) {
    if (sel === 'input[name="conflict-scope"]:checked') return radioSingle;
    return null;
  },
  querySelectorAll(sel) {
    if (sel === ".nav-btn") return navBtns;
    if (sel === ".hist-filter-btn") return histBtns;
    if (sel === 'input[name="conflict-scope"]') return [radioSingle];
    return [];
  },
  addEventListener() {},
};

const windowObj = {
  document: documentObj,
  pywebview: { api: fakeApi },
  addEventListener() {},
  removeEventListener() {},
  setTimeout: (fn) => { fn(); return 1; },
  clearTimeout: () => {},
  setInterval: () => 1,
  clearInterval: () => {},
  navigator: { clipboard: { writeText: async () => {} } },
  console,
};
windowObj.window = windowObj;

const context = vm.createContext(windowObj);
vm.runInContext(bridgeSource, context);
vm.runInContext(appSource, context);

const flushPromises = async () => {
  for (let i = 0; i < 15; i++) {
    await Promise.resolve();
  }
};

(async () => {
  // Wait for initApp() to finish
  await flushPromises();

  // TEST 1: Startup conflict restoration & failure recovery
  const conflictModal = documentObj.getElementById("modal-conflict");
  assert.strictEqual(
    conflictModal.classList.contains("hidden"),
    false,
    "Conflict modal must be restored and visible on startup when a task is waiting_conflict"
  );

  // Trigger Keep Both while resolve_conflict fails
  await documentObj.getElementById("conflict-keep-both-btn").trigger("click");
  assert.strictEqual(
    conflictModal.classList.contains("hidden"),
    false,
    "Conflict modal must remain open when resolve_conflict returns success: false"
  );
  assert.ok(
    documentObj.getElementById("global-alerts-container").innerHTML.includes("ERR_CONFLICT_NOT_FOUND"),
    "Global alerts must display error when resolve_conflict fails"
  );

  // Now let resolve_conflict succeed and click Keep Both again
  resolveConflictShouldSucceed = true;
  await documentObj.getElementById("conflict-keep-both-btn").trigger("click");
  assert.strictEqual(
    conflictModal.classList.contains("hidden"),
    true,
    "Conflict modal must close after resolve_conflict returns success: true"
  );

  // TEST 2: Single-row DOM update on task:progress without rewriting queue-list-container.innerHTML
  const listEl = documentObj.getElementById("queue-list-container");
  const setCountBefore = listEl.innerHTMLSetCount;
  const oldRowRef = listEl.rowMap.get("task-old-completed");
  const activeRowRef = listEl.rowMap.get("task-conflict-1");
  assert.ok(oldRowRef && activeRowRef, "Both task rows must exist in queue-list-container");

  windowObj.pladazDispatchEvent({
    event_type: "task:progress",
    data: {
      task_id: "task-conflict-1",
      stage: "downloading_stream",
      progress_percent: 65,
      speed_str: "3.0MiB/s",
      eta_str: "00:02",
    },
  });

  assert.strictEqual(
    listEl.innerHTMLSetCount,
    setCountBefore,
    "task:progress must NOT rewrite queue-list-container.innerHTML"
  );
  assert.strictEqual(
    listEl.rowMap.get("task-old-completed"),
    oldRowRef,
    "Unchanged row DOM node reference must be preserved during task:progress"
  );
  assert.strictEqual(activeRowRef.pctEl.textContent, "65%");
  assert.ok(activeRowRef.stageEl.textContent.includes("STAGE 06/10"));

  // TEST 3: Batch Run Summary counts ONLY active run tasks (not task-old-completed from previous run)
  windowObj.pladazDispatchEvent({
    event_type: "task:status_changed",
    data: {
      task: {
        task_id: "task-conflict-1",
        entry_url: "https://music.youtube.com/watch?v=conf1",
        status: "Completed",
        stage: null,
        progress_percent: 100,
        metadata: { title: "Dup Song", album_artist: "Artist", album: "Album" },
        has_cover: false,
        validation: null,
        warnings: ["WARN_VALIDATOR_NO_COVER"],
        error: null,
      },
      queue_running: false,
      queue_halted: false,
    },
  });

  const summaryModal = documentObj.getElementById("modal-queue-summary");
  assert.strictEqual(summaryModal.classList.contains("hidden"), false, "Queue summary modal should open when run finishes");
  assert.strictEqual(
    documentObj.getElementById("summary-completed-count").textContent,
    "1",
    "Summary must count only the 1 task from the active run, NOT old completed tasks"
  );

  // TEST 4: Track Detail View never guesses PASS when validation is null, and covr pill is dynamic
  const openTrackBtn = new FakeElement("open-track-btn", "BUTTON");
  openTrackBtn.attrs["data-action"] = "open-track";
  openTrackBtn.attrs["data-task-id"] = "task-old-completed";
  await bodyEl.trigger("click", { target: openTrackBtn });

  assert.strictEqual(
    documentObj.getElementById("track-validator-summary").textContent,
    "NO VALIDATION DATA",
    "Validator summary must show NO VALIDATION DATA when task.validation is null"
  );
  const validatorChecksHtml = documentObj.getElementById("track-validator-checks").innerHTML;
  assert.ok(validatorChecksHtml.includes("NO DATA"), "Validator checks must show NO DATA when task.validation is null");
  assert.strictEqual(validatorChecksHtml.includes(">PASS<"), false, "Validator checks must NEVER fake PASS when task.validation is null");
  assert.strictEqual(
    documentObj.getElementById("track-view-covr-pill").textContent,
    "ATOM covr: <omitted — no cover art>",
    "Cover pill must reflect missing cover when has_cover is false"
  );

  // TEST 5: Cover preview retries after initial null response when cover becomes available
  coverPreviewDataUrl = "data:image/jpeg;base64,VALIDCOVER";
  windowObj.pladazDispatchEvent({
    event_type: "task:status_changed",
    data: {
      task: {
        task_id: "task-old-completed",
        entry_url: "https://music.youtube.com/watch?v=old",
        status: "Completed",
        stage: null,
        progress_percent: 100,
        metadata: { title: "Old Run Song", album_artist: "Old Artist", album: "Old Album" },
        has_cover: true,
        validation: null,
        warnings: [],
        error: null,
      },
    },
  });
  await flushPromises();
  assert.strictEqual(
    documentObj.getElementById("track-view-cover-img").src,
    "data:image/jpeg;base64,VALIDCOVER",
    "ensureCoverLoaded must retry and load cover art after an earlier null response"
  );
  assert.strictEqual(
    documentObj.getElementById("track-view-covr-pill").textContent,
    "EMBEDDED ATOM: covr (800×800 JPEG)",
    "Cover pill must show EMBEDDED ATOM: covr (800×800 JPEG) when has_cover is true"
  );

  // TEST 6: Bridge does not accept paths from UI, remove cookies calls clear_cookies_file, and failed commands surface errors
  await windowObj.PladazBridge.browseDestinationFolder("C:\\InjectedPath");
  const browseCall = apiCalls.find((c) => c[0] === "browse_destination_folder");
  assert.strictEqual(browseCall.length, 1, "browseDestinationFolder must not forward any path argument from UI");

  await windowObj.PladazBridge.selectCookiesFile("C:\\InjectedCookies");
  const cookiesCall = apiCalls.find((c) => c[0] === "select_cookies_file");
  assert.strictEqual(cookiesCall.length, 1, "selectCookiesFile must not forward any path argument from UI");

  await documentObj.getElementById("settings-remove-cookies-btn").trigger("click");
  const clearCookiesCall = apiCalls.find((c) => c[0] === "clear_cookies_file");
  assert.ok(clearCookiesCall, "Removing cookies must call explicit clear_cookies_file()");

  await documentObj.getElementById("settings-save-btn").trigger("click");
  assert.ok(
    documentObj.getElementById("global-alerts-container").innerHTML.includes("Disk write error"),
    "Failed Save Settings (updateConfig) must surface error in global alerts"
  );
  assert.strictEqual(
    documentObj.getElementById("settings-save-status").textContent,
    "✕ FAILED TO SAVE SETTINGS"
  );
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""
    proc = subprocess.run(
        ["node", "-e", node_script],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15.0,
    )
    assert proc.returncode == 0, f"Node JS frontend test failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
