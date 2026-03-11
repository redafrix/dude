from __future__ import annotations

import json


def render_remote_app_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#c95b2c">
  <title>Dude Remote</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <style>
    :root {
      --bg: #f4efe6;
      --panel: rgba(255, 251, 245, 0.88);
      --ink: #1f2630;
      --muted: #5f6874;
      --accent: #c95b2c;
      --accent-deep: #9b3e18;
      --border: rgba(31, 38, 48, 0.12);
      --shadow: 0 18px 60px rgba(35, 28, 20, 0.15);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Source Sans 3", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(201, 91, 44, 0.18), transparent 32%),
        radial-gradient(circle at bottom right, rgba(53, 90, 122, 0.16), transparent 28%),
        linear-gradient(180deg, #faf5ed, #efe7db);
      padding: 20px;
    }
    .shell {
      max-width: 1180px;
      margin: 0 auto;
      display: grid;
      gap: 18px;
    }
    .hero, .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    .hero {
      padding: 28px;
      overflow: hidden;
      position: relative;
    }
    .hero::after {
      content: "";
      position: absolute;
      right: -80px;
      top: -60px;
      width: 240px;
      height: 240px;
      background: radial-gradient(circle, rgba(201, 91, 44, 0.28), transparent 68%);
      pointer-events: none;
    }
    h1 {
      margin: 0 0 8px;
      font-size: clamp(2rem, 4vw, 3.6rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }
    .sub {
      margin: 0;
      max-width: 780px;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.5;
    }
    .grid {
      display: grid;
      gap: 18px;
      grid-template-columns: 1.3fr 0.9fr;
    }
    .panel {
      padding: 20px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 1.05rem;
      letter-spacing: -0.02em;
    }
    label {
      display: block;
      font-size: 0.88rem;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input, select, textarea, button {
      font: inherit;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
    }
    textarea {
      min-height: 116px;
      resize: vertical;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 180px;
      gap: 12px;
      align-items: end;
    }
    .actions, .mini-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 11px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      box-shadow: 0 10px 24px rgba(201, 91, 44, 0.24);
    }
    button.secondary {
      background: #e5ded2;
      color: var(--ink);
      box-shadow: none;
    }
    button.ghost {
      background: transparent;
      color: var(--accent-deep);
      border: 1px solid rgba(201, 91, 44, 0.22);
      box-shadow: none;
    }
    .inline {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    .inline input[type="checkbox"] {
      width: auto;
      margin: 0;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(201, 91, 44, 0.1);
      color: var(--accent-deep);
      font-size: 0.88rem;
      margin-bottom: 14px;
    }
    pre, .card-list {
      margin: 0;
      border-radius: 16px;
      background: rgba(28, 37, 47, 0.92);
      color: #eef2f7;
      padding: 14px;
      overflow: auto;
    }
    .card-list {
      display: grid;
      gap: 10px;
    }
    .task-card {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      padding: 12px;
    }
    .task-card strong {
      display: block;
      margin-bottom: 6px;
    }
    .meta {
      color: #b8c3cf;
      font-size: 0.84rem;
    }
    .browser-shot {
      margin-top: 14px;
      width: 100%;
      min-height: 220px;
      object-fit: cover;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(201, 91, 44, 0.1), rgba(34, 58, 78, 0.12));
      border: 1px solid var(--border);
    }
    @media (max-width: 920px) {
      .grid { grid-template-columns: 1fr; }
      .row { grid-template-columns: 1fr; }
      body { padding: 14px; }
      .hero, .panel { border-radius: 20px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <p class="status-pill">Remote transport bootstrap • local API • Android-ready PWA path</p>
      <h1>Dude Remote</h1>
      <p class="sub">
        This is the first phone-friendly control surface for Dude. It talks to the same task,
        approval, audit, browser-state, and desktop-capture API that the CLI uses. Store the
        bearer token locally in this device, send a task, approve it when needed, and inspect the
        latest browser or screen artifact.
      </p>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Task Console</h2>
        <label for="token">Bearer Token</label>
        <input id="token" type="password" placeholder="Paste the token from dude remote-token">

        <div class="row" style="margin-top: 14px;">
          <div>
            <label for="taskText">Task</label>
            <textarea
              id="taskText"
              placeholder="Try: download discord, open browser, or show current activity"
            ></textarea>
          </div>
          <div>
            <label for="backend">Backend</label>
            <select id="backend">
              <option value="auto">auto</option>
              <option value="local">local</option>
              <option value="codex">codex</option>
              <option value="gemini">gemini</option>
            </select>
            <div class="inline">
              <input id="autoApprove" type="checkbox">
              <label for="autoApprove" style="margin: 0;">Auto-approve</label>
            </div>
            <div class="inline">
              <input id="voiceReply" type="checkbox" checked>
              <label for="voiceReply" style="margin: 0;">Voice reply</label>
            </div>
          </div>
        </div>

        <div class="actions">
          <button id="sendTask">Send Task</button>
          <button id="approveLatest" class="secondary">Approve Latest</button>
          <button id="startVoice" class="secondary">Start Voice Note</button>
          <button id="stopVoice" class="ghost">Stop Voice Note</button>
          <button id="captureScreen" class="secondary">Capture Screen</button>
          <button id="recordScreen" class="secondary">Record 6s Clip</button>
          <button id="startLiveScreen" class="secondary">Start Live Screen</button>
          <button id="stopLiveScreen" class="ghost">Stop Live Screen</button>
          <button id="refreshAudit" class="ghost">Refresh Audit</button>
          <button id="refreshMemory" class="ghost">Refresh Memory</button>
          <button id="refreshBrowser" class="ghost">Refresh Browser State</button>
          <button id="refreshScreen" class="ghost">Refresh Screen State</button>
        </div>

        <h2 style="margin-top: 20px;">Latest Response</h2>
        <pre id="taskResult">No task submitted yet.</pre>
        <audio
          id="replyAudio"
          controls
          style="width: 100%; margin-top: 14px; display: none;"
        ></audio>
      </div>

      <div style="display: grid; gap: 18px;">
        <div class="panel">
          <h2>Browser State</h2>
          <pre id="browserState">No browser state fetched yet.</pre>
          <img id="browserShot" class="browser-shot" alt="Latest browser screenshot">
        </div>

        <div class="panel">
          <h2>Screen State</h2>
          <pre id="screenState">No desktop capture fetched yet.</pre>
          <img id="screenShot" class="browser-shot" alt="Latest desktop capture">
          <video id="screenVideo" class="browser-shot" controls style="display: none;"></video>
        </div>

        <div class="panel">
          <h2>Recent Audit</h2>
          <div id="auditList" class="card-list"></div>
        </div>

        <div class="panel">
          <h2>Memory</h2>
          <label for="memoryNote">Add Note</label>
          <textarea
            id="memoryNote"
            placeholder="Save a persistent note or preference for later."
            style="min-height: 88px;"
          ></textarea>
          <div class="mini-actions">
            <button id="saveMemory" class="secondary">Save Note</button>
            <button id="clearMemory" class="ghost">Clear Memory</button>
          </div>
          <div id="memoryList" class="card-list" style="margin-top: 14px;"></div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const tokenInput = document.getElementById("token");
    const taskText = document.getElementById("taskText");
    const backendSelect = document.getElementById("backend");
    const autoApprove = document.getElementById("autoApprove");
    const taskResult = document.getElementById("taskResult");
    const replyAudio = document.getElementById("replyAudio");
    const browserState = document.getElementById("browserState");
    const browserShot = document.getElementById("browserShot");
    const screenState = document.getElementById("screenState");
    const screenShot = document.getElementById("screenShot");
    const screenVideo = document.getElementById("screenVideo");
    const auditList = document.getElementById("auditList");
    const memoryNote = document.getElementById("memoryNote");
    const memoryList = document.getElementById("memoryList");
    const voiceReply = document.getElementById("voiceReply");
    let activeRecorder = null;
    let activeStream = null;
    let activeChunks = [];

    const STORE_KEY = "dude-remote-token";
    tokenInput.value = localStorage.getItem(STORE_KEY) || "";
    tokenInput.addEventListener("change", () => {
      localStorage.setItem(STORE_KEY, tokenInput.value.trim());
    });

    async function fetchJson(path, options = {}) {
      const token = tokenInput.value.trim();
      const headers = new Headers(options.headers || {});
      if (token) headers.set("Authorization", `Bearer ${token}`);
      if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
      const response = await fetch(path, { ...options, headers });
      const text = await response.text();
      let payload = {};
      try { payload = text ? JSON.parse(text) : {}; } catch { payload = { raw: text }; }
      if (!response.ok) {
        throw new Error(payload.error || payload.raw || `HTTP ${response.status}`);
      }
      return payload;
    }

    async function refreshAudit() {
      try {
        const payload = await fetchJson("/audit?limit=8");
        const tasks = payload.tasks || [];
        auditList.innerHTML = "";
        if (!tasks.length) {
          auditList.textContent = "No tasks yet.";
          return;
        }
        for (const task of tasks) {
          const card = document.createElement("article");
          card.className = "task-card";
          const taskOutput = task.output_text || task.error_text || "No output yet.";
          card.innerHTML = `
            <strong>${task.request_text || "(empty task)"}</strong>
            <div class="meta">${task.status} • ${task.backend} • ${task.approval_class}</div>
            <div style="margin-top:8px;">${taskOutput}</div>
          `;
          auditList.appendChild(card);
        }
      } catch (error) {
        auditList.textContent = String(error.message || error);
      }
    }

    async function refreshMemory() {
      try {
        const payload = await fetchJson("/memory?limit=10");
        const entries = payload.memory || [];
        memoryList.innerHTML = "";
        if (!entries.length) {
          memoryList.textContent = "No memory entries yet.";
          return;
        }
        for (const entry of entries) {
          const card = document.createElement("article");
          card.className = "task-card";
          const detailText = entry.detail && entry.detail.text ? entry.detail.text : "";
          card.innerHTML = `
            <strong>${entry.summary_text || "(empty memory)"}</strong>
            <div class="meta">${entry.kind} • ${entry.memory_id}</div>
            <div style="margin-top:8px;">${detailText}</div>
          `;
          const actions = document.createElement("div");
          actions.className = "mini-actions";
          const deleteButton = document.createElement("button");
          deleteButton.className = "ghost";
          deleteButton.textContent = "Delete";
          deleteButton.addEventListener("click", () => deleteMemory(entry.memory_id));
          actions.appendChild(deleteButton);
          card.appendChild(actions);
          memoryList.appendChild(card);
        }
      } catch (error) {
        memoryList.textContent = String(error.message || error);
      }
    }

    async function refreshBrowserState() {
      try {
        const payload = await fetchJson("/browser/state");
        browserState.textContent = JSON.stringify(payload.browser, null, 2);
        const token = tokenInput.value.trim();
        const response = await fetch("/browser/last-screenshot", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (response.ok) {
          const blob = await response.blob();
          browserShot.src = URL.createObjectURL(blob);
          browserShot.style.display = "block";
        } else {
          browserShot.removeAttribute("src");
          browserShot.style.display = "none";
        }
      } catch (error) {
        browserState.textContent = String(error.message || error);
        browserShot.removeAttribute("src");
        browserShot.style.display = "none";
      }
    }

    async function refreshScreenState() {
      try {
        const payload = await fetchJson("/screen/state");
        screenState.textContent = JSON.stringify(payload.screen, null, 2);
        const token = tokenInput.value.trim();
        const response = await fetch("/screen/latest-artifact", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const contentType = response.headers.get("Content-Type", "");
        if (response.ok && contentType.startsWith("image/")) {
          const blob = await response.blob();
          screenShot.src = URL.createObjectURL(blob);
          screenShot.style.display = "block";
          screenVideo.removeAttribute("src");
          screenVideo.style.display = "none";
        } else if (response.ok && contentType.startsWith("video/")) {
          const blob = await response.blob();
          screenVideo.src = URL.createObjectURL(blob);
          screenVideo.style.display = "block";
          screenShot.removeAttribute("src");
          screenShot.style.display = "none";
        } else {
          screenShot.removeAttribute("src");
          screenShot.style.display = "none";
          screenVideo.removeAttribute("src");
          screenVideo.style.display = "none";
        }
      } catch (error) {
        screenState.textContent = String(error.message || error);
        screenShot.removeAttribute("src");
        screenShot.style.display = "none";
        screenVideo.removeAttribute("src");
        screenVideo.style.display = "none";
      }
    }

    async function startLiveScreen() {
      stopLiveScreen(false);
      const token = tokenInput.value.trim();
      if (!token) {
        throw new Error("Enter the remote token first.");
      }
      const streamUrl = `/screen/live.mjpeg?token=${encodeURIComponent(token)}&ts=${Date.now()}`;
      screenShot.onerror = () => {
        stopLiveScreen(false);
        taskResult.textContent = "Live screen stream failed.";
      };
      screenShot.src = streamUrl;
      screenShot.style.display = "block";
      screenVideo.removeAttribute("src");
      screenVideo.style.display = "none";
      taskResult.textContent = "Live screen stream started.";
    }

    function stopLiveScreen(updateStatus = true) {
      screenShot.onerror = null;
      screenShot.removeAttribute("src");
      if (updateStatus) {
        taskResult.textContent = "Live screen view stopped.";
      }
    }

    async function refreshReplyAudio(autoPlay = false) {
      try {
        const token = tokenInput.value.trim();
        const response = await fetch("/reply/latest-audio", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!response.ok) {
          replyAudio.removeAttribute("src");
          replyAudio.style.display = "none";
          return;
        }
        const blob = await response.blob();
        replyAudio.src = URL.createObjectURL(blob);
        replyAudio.style.display = "block";
        if (autoPlay) {
          await replyAudio.play().catch(() => {});
        }
      } catch {
        replyAudio.removeAttribute("src");
        replyAudio.style.display = "none";
      }
    }

    async function submitTask() {
      taskResult.textContent = "Working...";
      try {
        const payload = await fetchJson("/task", {
          method: "POST",
          body: JSON.stringify({
            text: taskText.value.trim(),
            backend: backendSelect.value,
            auto_approve: autoApprove.checked,
            voice_reply: voiceReply.checked,
          }),
        });
        taskResult.textContent = JSON.stringify(payload.task, null, 2);
        await refreshAudit();
        await refreshMemory();
        await refreshBrowserState();
        await refreshScreenState();
        if (payload.reply) {
          await refreshReplyAudio(true);
        }
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    async function approveLatest() {
      taskResult.textContent = "Approving latest pending task...";
      try {
        const payload = await fetchJson("/approve", {
          method: "POST",
          body: JSON.stringify({ latest: true }),
        });
        taskResult.textContent = JSON.stringify(payload.task, null, 2);
        await refreshAudit();
        await refreshMemory();
        await refreshBrowserState();
        await refreshScreenState();
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    async function sendVoiceBlob(blob) {
      taskResult.textContent = "Uploading voice note...";
      try {
        const token = tokenInput.value.trim();
        const response = await fetch(
          `/voice/task?backend=${backendSelect.value}&auto_approve=${autoApprove.checked}&voice_reply=${voiceReply.checked}`,
          {
            method: "POST",
            headers: {
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
              "Content-Type": blob.type || "application/octet-stream",
            },
            body: blob,
          },
        );
        const text = await response.text();
        const payload = text ? JSON.parse(text) : {};
        if (!response.ok) {
          throw new Error(payload.error || `HTTP ${response.status}`);
        }
        taskResult.textContent = JSON.stringify(payload, null, 2);
        await refreshAudit();
        await refreshMemory();
        await refreshBrowserState();
        await refreshScreenState();
        if (payload.reply) {
          await refreshReplyAudio(true);
        }
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    async function startVoiceNote() {
      if (!navigator.mediaDevices || !window.MediaRecorder) {
        taskResult.textContent = "This browser does not support voice-note recording.";
        return;
      }
      if (activeRecorder) {
        taskResult.textContent = "Voice-note recording is already in progress.";
        return;
      }
      try {
        activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        activeChunks = [];
        activeRecorder = new MediaRecorder(activeStream);
        activeRecorder.ondataavailable = event => {
          if (event.data && event.data.size > 0) {
            activeChunks.push(event.data);
          }
        };
        activeRecorder.onstop = async () => {
          const blob = new Blob(activeChunks, { type: activeRecorder.mimeType || "audio/webm" });
          activeStream.getTracks().forEach(track => track.stop());
          activeStream = null;
          activeRecorder = null;
          await sendVoiceBlob(blob);
        };
        activeRecorder.start();
        taskResult.textContent = "Recording voice note...";
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    function stopVoiceNote() {
      if (!activeRecorder) {
        taskResult.textContent = "No voice-note recording is active.";
        return;
      }
      activeRecorder.stop();
    }

    async function quickTask(text, auto = true) {
      taskText.value = text;
      autoApprove.checked = auto;
      await submitTask();
    }

    async function saveMemoryNote() {
      const text = memoryNote.value.trim();
      if (!text) {
        taskResult.textContent = "Enter a memory note first.";
        return;
      }
      taskResult.textContent = "Saving memory note...";
      try {
        const payload = await fetchJson("/memory/note", {
          method: "POST",
          body: JSON.stringify({ text }),
        });
        memoryNote.value = "";
        taskResult.textContent = JSON.stringify(payload.memory, null, 2);
        await refreshMemory();
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    async function deleteMemory(memoryId) {
      taskResult.textContent = `Deleting memory ${memoryId}...`;
      try {
        const payload = await fetchJson("/memory/delete", {
          method: "POST",
          body: JSON.stringify({ memory_id: memoryId }),
        });
        taskResult.textContent = JSON.stringify(payload, null, 2);
        await refreshMemory();
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    async function clearMemory() {
      taskResult.textContent = "Clearing memory...";
      try {
        const payload = await fetchJson("/memory/clear", {
          method: "POST",
          body: JSON.stringify({}),
        });
        taskResult.textContent = JSON.stringify(payload, null, 2);
        await refreshMemory();
      } catch (error) {
        taskResult.textContent = String(error.message || error);
      }
    }

    document.getElementById("sendTask").addEventListener("click", submitTask);
    document.getElementById("approveLatest").addEventListener("click", approveLatest);
    document.getElementById("startVoice").addEventListener("click", startVoiceNote);
    document.getElementById("stopVoice").addEventListener("click", stopVoiceNote);
    document.getElementById("captureScreen").addEventListener("click", () => {
      stopLiveScreen(false);
      quickTask("take a screenshot", true);
    });
    document.getElementById("recordScreen").addEventListener("click", () => {
      stopLiveScreen(false);
      quickTask("record screen for 6 seconds", true);
    });
    document.getElementById("startLiveScreen").addEventListener("click", startLiveScreen);
    document.getElementById("stopLiveScreen").addEventListener("click", () => stopLiveScreen(true));
    document.getElementById("refreshAudit").addEventListener("click", refreshAudit);
    document.getElementById("refreshMemory").addEventListener("click", refreshMemory);
    document.getElementById("refreshBrowser").addEventListener("click", refreshBrowserState);
    document.getElementById("refreshScreen").addEventListener("click", refreshScreenState);
    document.getElementById("saveMemory").addEventListener("click", saveMemoryNote);
    document.getElementById("clearMemory").addEventListener("click", clearMemory);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    }

    refreshAudit();
    refreshMemory();
    refreshBrowserState();
    refreshScreenState();
  </script>
</body>
</html>
"""


def render_manifest() -> str:
    return json.dumps(
        {
            "name": "Dude Remote",
            "short_name": "Dude",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#f4efe6",
            "theme_color": "#c95b2c",
            "description": "Remote control surface for the Dude assistant.",
        },
        indent=2,
    )


def render_service_worker() -> str:
    return """self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});
"""
