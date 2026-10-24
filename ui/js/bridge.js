/**
 * PLADAZ JS Bridge Client (SYSTEM_DESIGN.md 2.6, 3.3)
 * Wraps window.pywebview.api.* and handles window.pladazDispatchEvent for all 6 backend events.
 */
(function() {
    "use strict";

    const EVENT_NAMES = [
        "queue:updated",
        "task:progress",
        "task:status_changed",
        "task:conflict_prompt",
        "sdcard:status_changed",
        "system:error",
    ];

    const listeners = {};
    EVENT_NAMES.forEach((evt) => {
        listeners[evt] = new Set();
    });

    function on(eventName, callback) {
        if (!listeners[eventName]) {
            listeners[eventName] = new Set();
        }
        listeners[eventName].add(callback);
        return function unsubscribe() {
            listeners[eventName].delete(callback);
        };
    }

    function emitLocal(eventName, data) {
        const set = listeners[eventName];
        if (!set) return;
        set.forEach((fn) => {
            try {
                fn(data || {});
            } catch (err) {
                console.error("[PLADAZ Bridge] Listener error on", eventName, err);
            }
        });
    }

    /**
     * Global entrypoint invoked by Python EventDispatcher via window.evaluate_js.
     * Supports both:
     *   window.pladazDispatchEvent({ event_type: "...", data: {...} })
     * and:
     *   window.pladazDispatchEvent("...", {...})
     */
    window.pladazDispatchEvent = function(firstArg, secondArg) {
        if (typeof firstArg === "string") {
            emitLocal(firstArg, secondArg || {});
            return;
        }
        if (firstArg && typeof firstArg === "object" && typeof firstArg.event_type === "string") {
            emitLocal(firstArg.event_type, firstArg.data || {});
        }
    };

    function waitForPywebview(methodName, timeoutMs = 6000) {
        return new Promise((resolve) => {
            const isReady = () =>
                Boolean(
                    window.pywebview &&
                    window.pywebview.api &&
                    (!methodName || typeof window.pywebview.api[methodName] === "function")
                );

            if (isReady()) {
                resolve(window.pywebview.api);
                return;
            }
            let settled = false;
            let pollTimer = null;
            const finish = (apiObj) => {
                if (settled) return;
                settled = true;
                window.removeEventListener("pywebviewready", onReady);
                if (pollTimer) clearInterval(pollTimer);
                resolve(apiObj);
            };
            const onReady = () => {
                if (isReady()) {
                    finish(window.pywebview.api);
                }
            };
            window.addEventListener("pywebviewready", onReady);
            pollTimer = setInterval(() => {
                if (isReady()) {
                    finish(window.pywebview.api);
                }
            }, 40);
            setTimeout(() => {
                finish(window.pywebview ? window.pywebview.api : null);
            }, timeoutMs);
        });
    }

    async function callApi(methodName, ...args) {
        const api = await waitForPywebview(methodName);
        if (!api || typeof api[methodName] !== "function") {
            return {
                success: false,
                error: {
                    code: "ERR_BRIDGE_UNAVAILABLE",
                    message_en: `Native bridge method '${methodName}' is unavailable.`,
                    recoverable: true,
                },
            };
        }
        try {
            const res = await api[methodName](...args);
            return res || { success: false };
        } catch (err) {
            return {
                success: false,
                error: {
                    code: "ERR_BRIDGE_CALL_FAILED",
                    message_en: err && err.message ? String(err.message) : "Bridge call failed.",
                    recoverable: true,
                },
            };
        }
    }

    window.PladazBridge = {
        on,
        emitLocal,
        getInitialState: () => callApi("get_initial_state"),
        acceptDisclaimer: () => callApi("accept_disclaimer"),
        scanStorageDevices: () => callApi("scan_storage_devices"),
        browseDestinationFolder: () => callApi("browse_destination_folder"),
        selectDetectedDrive: (driveRoot) => callApi("select_detected_drive", driveRoot),
        updateConfig: (partial) => callApi("update_config", partial),
        selectCookiesFile: () => callApi("select_cookies_file"),
        clearCookiesFile: () => callApi("clear_cookies_file"),
        detectSupportedBrowsers: () => callApi("detect_supported_browsers"),
        testBrowserCookies: (browser) => callApi("test_browser_cookies", browser),
        selectBrowserCookies: (browser) => callApi("select_browser_cookies", browser),
        clearBrowserCookies: () => callApi("clear_browser_cookies"),
        checkYtdlpStatus: () => callApi("check_ytdlp_status"),
        locateYtdlpFile: () => callApi("locate_ytdlp_file"),
        updateYtdlpModule: () => callApi("update_ytdlp_module"),
        enqueueUrls: (urlText) => callApi("enqueue_urls", urlText),
        startQueue: () => callApi("start_queue"),
        cancelTask: (taskId) => callApi("cancel_task", taskId),
        resumeQueue: () => callApi("resume_queue"),
        resolveConflict: (taskId, action, scope) =>
            callApi("resolve_conflict", taskId, action, scope || "single"),
        retryTask: (taskId) => callApi("retry_task", taskId),
        removeTask: (taskId) => callApi("remove_task", taskId),
        clearCompletedTasks: () => callApi("clear_completed_tasks"),
        getHistory: () => callApi("get_history"),
        clearHistory: () => callApi("clear_history"),
        getCoverPreview: (taskId) => callApi("get_cover_preview", taskId),
        getRecentLogs: (maxLines = 80) => callApi("get_recent_logs", maxLines),
        openFolder: (target = "destination") => callApi("open_folder", target),
        quitApp: () => callApi("quit_app"),
    };
})();