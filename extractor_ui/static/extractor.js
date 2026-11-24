(function () {
  "use strict";

  const API = "/extractor/api/runs";
  const POLL_MS = 1000;
  const HEADERS = { "Content-Type": "application/json", "X-Agri-Dashboard": "1" };
  const LABELS = {
    idle: "Idle", running: "Running", waiting: "Waiting for you",
    completed: "Completed", failed: "Failed",
  };

  const byId = (id) => document.getElementById(id);
  const form = byId("run-form");
  const requestBox = byId("request");
  const dryRun = byId("dry-run");
  const runButton = byId("run-button");
  const formError = byId("form-error");
  const statusPill = byId("status");
  const runMeta = byId("run-meta");
  const log = byId("log");
  const result = byId("result");
  const resultTitle = byId("result-title");
  const resultText = byId("result-text");
  const dialog = byId("clarify");
  const clarifyMessage = byId("clarify-message");
  const clarifyOptions = byId("clarify-options");
  const clarifyCancel = byId("clarify-cancel");

  const HISTORY = "/extractor/api/history";
  const historyTable = byId("history-table");
  const historyBody = byId("history-body");
  const historyEmpty = byId("history-empty");
  const historyError = byId("history-error");
  const historyPager = byId("history-pager");
  const historyPage = byId("history-page");
  const historyPrev = byId("history-prev");
  const historyNext = byId("history-next");
  const details = byId("details");
  const detailsList = byId("details-list");
  const detailsLog = byId("details-log");
  let currentPage = 1;
  let totalPages = 1;

  let runId = null;
  let next = 0;
  let timer = null;
  let promptShown = false;

  function setStatus(status) {
    statusPill.textContent = LABELS[status] || status;
    statusPill.className = "pill " + status;
  }

  function showError(message) {
    formError.textContent = message || "";
    formError.hidden = !message;
  }

  function resetView(run) {
    log.textContent = "";
    result.hidden = true;
    next = 0;
    promptShown = false;
    runMeta.hidden = false;
    runMeta.textContent = (run.dry_run ? "Dry run" : "Writes to MongoDB") + " — " + run.request;
  }

  function appendLogs(lines) {
    if (!lines.length) return;
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
    log.textContent += lines.map((l) => l.time + "  " + l.text).join("\n") + "\n";
    if (stick) log.scrollTop = log.scrollHeight;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(poll, POLL_MS);
  }

  async function api(url, options) {
    const response = await fetch(url, Object.assign({ headers: HEADERS }, options));
    let body = {};
    try { body = await response.json(); } catch (_) { /* non-JSON error page */ }
    if (!response.ok) throw new Error(body.error || "Request failed (" + response.status + ").");
    return body;
  }

  function render(run) {
    appendLogs(run.logs);
    next = run.next;
    setStatus(run.status);
    const active = run.status === "running" || run.status === "waiting";
    runButton.disabled = active;

    if (run.status === "waiting" && run.prompt && !promptShown) {
      showPrompt(run.prompt);
    } else if (run.status !== "waiting" && dialog.open) {
      dialog.close();
    }

    if (!active) {
      result.hidden = false;
      resultTitle.textContent = run.status === "failed" ? "Error" : "Result";
      resultText.textContent = run.error || run.answer || "(no answer)";
    }
    return active;
  }

  async function poll() {
    if (!runId) return;
    try {
      const run = await api(API + "/" + runId + "?after=" + next);
      if (render(run)) schedule();
      else loadHistory(1);
    } catch (error) {
      showError(error.message);
      schedule();
    }
  }

  function showPrompt(prompt) {
    promptShown = true;
    clarifyMessage.textContent = prompt.message;
    clarifyOptions.replaceChildren();
    prompt.options.forEach((option) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = option.number + ". " + option.label;
      button.addEventListener("click", () => answer(option.number));
      clarifyOptions.appendChild(button);
    });
    if (!dialog.open) dialog.showModal();
  }

  async function answer(choice) {
    try {
      await api(API + "/" + runId + "/choice", {
        method: "POST", body: JSON.stringify({ choice: choice }),
      });
      dialog.close();
      promptShown = false;
      showError("");
      schedule();
    } catch (error) {
      showError(error.message);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const text = requestBox.value.trim();
    if (!text) { showError("Enter a request."); return; }
    runButton.disabled = true;
    try {
      const run = await api(API, {
        method: "POST",
        body: JSON.stringify({ request: text, dry_run: dryRun.checked }),
      });
      runId = run.run_id;
      resetView(run);
      render(run);
      schedule();
    } catch (error) {
      showError(error.message);
      runButton.disabled = false;
    }
  });

  function cell(row, text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    row.appendChild(td);
    return td;
  }

  async function loadHistory(page) {
    try {
      const data = await api(HISTORY + "?page=" + page);
      currentPage = data.page;
      totalPages = data.pages;
      historyError.hidden = true;
      historyBody.replaceChildren();
      data.items.forEach((item) => {
        const row = document.createElement("tr");
        cell(row, (item.started_at || "").replace("T", " ").replace("+00:00", ""));
        cell(row, item.human_input + (item.is_human_input_overridden ? "  (overridden)" : ""), "request");
        cell(row, item.dry_run ? "Dry run" : "Write");
        cell(row, item.status);
        const action = document.createElement("td");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = "View details";
        button.addEventListener("click", () => showDetails(item.run_id));
        action.appendChild(button);
        row.appendChild(action);
        historyBody.appendChild(row);
      });
      historyTable.hidden = data.items.length === 0;
      historyEmpty.hidden = data.items.length !== 0;
      historyPager.hidden = data.total <= data.page_size;
      historyPage.textContent = "Page " + data.page + " of " + data.pages + " — " + data.total + " runs";
      historyPrev.disabled = data.page <= 1;
      historyNext.disabled = data.page >= data.pages;
    } catch (error) {
      historyError.textContent = error.message;
      historyError.hidden = false;
    }
  }

  function addDetail(label, value) {
    if (value === null || value === undefined || value === "") return;
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    detailsList.append(dt, dd);
  }

  async function showDetails(id) {
    try {
      const doc = await api(HISTORY + "/" + encodeURIComponent(id));
      detailsList.replaceChildren();
      addDetail("Human input", doc.human_input);
      addDetail("Input overridden", doc.is_human_input_overridden ? "Yes" : "No");
      addDetail("Overridden input", doc.overridden_input);
      addDetail("Mode", doc.dry_run ? "Dry run" : "Write");
      addDetail("Tool", doc.tool);
      addDetail("Status", doc.status);
      addDetail("Started (UTC)", doc.started_at);
      addDetail("Finished (UTC)", doc.finished_at);
      addDetail("Result", doc.result);
      addDetail("Error", doc.error);
      detailsLog.textContent = (doc.logs || []).map((l) => l.time + "  " + l.text).join("\n");
      if (!details.open) details.showModal();
    } catch (error) {
      historyError.textContent = error.message;
      historyError.hidden = false;
    }
  }

  historyPrev.addEventListener("click", () => loadHistory(currentPage - 1));
  historyNext.addEventListener("click", () => loadHistory(currentPage + 1));
  byId("details-close").addEventListener("click", () => details.close());
  loadHistory(1);

  clarifyCancel.addEventListener("click", () => answer(null));
  // Escape closes a modal dialog; treat it as cancelling the run's question.
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); answer(null); });

  // Reattach to the latest run after a page reload.
  (async function restore() {
    try {
      const run = await api(API + "/latest");
      runId = run.run_id;
      resetView(run);
      requestBox.value = run.request;
      dryRun.checked = run.dry_run;
      if (render(run)) schedule();
    } catch (_) { /* no previous run */ }
  })();
})();