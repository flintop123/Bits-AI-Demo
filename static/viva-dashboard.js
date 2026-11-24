(() => {
  const byId = (id) => document.getElementById(id);
  const upload = byId("viva-upload-form");
  if (!upload) return;
  const evidence = byId("viva-evidence");
  const file = byId("viva-pdf");
  const save = byId("viva-save");
  const status = byId("viva-status");
  const reopen = byId("viva-reopen-form");
  const runInput = byId("viva-run-id");
  const pageSize = 8;
  let active = null;
  let sourceUrl = null;
  let offset = 0;
  let busy = false;

  function node(tag, text) {
    const el = document.createElement(tag);
    el.textContent = text;
    return el;
  }
  function clearSource() {
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl = null;
  }
  function setBusy(value) {
    busy = value;
    evidence.setAttribute("aria-busy", String(value));
    [...upload.elements, ...reopen.elements].forEach((element) => { element.disabled = value; });
    save.disabled = value || active?.status !== "preview" || !active.valid_count;
  }
  async function api(path, options) {
    const response = await fetch(`/api/v1/viva/uploads${path}`, {
      ...options, headers: { "X-Agri-Dashboard": "1" }, cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `The request failed (HTTP ${response.status}).`);
    return payload;
  }
  function renderRecords() {
    if (!active) return;
    const title = active.status === "verified" ? "Saved from MongoDB" : "Validated preview";
    const records = active.records || [];
    const end = Math.min(offset + pageSize, records.length);
    const board = byId("viva-records");
    board.replaceChildren();
    records.slice(offset, end).forEach((record) => {
      const article = document.createElement("article");
      article.className = "viva-record";
      article.append(node("h3", `Page ${record.page_number} · Chunk ${record.chunk_index}`));
      article.append(node("small", `${title} · ${record.extraction_method} · ${record.language}`));
      if (sourceUrl) {
        const link = node("a", "Open source page");
        link.href = `${sourceUrl}#page=${Number(record.page_number)}`;
        link.target = "_blank";
        link.rel = "noopener";
        article.append(link);
      }
      const content = node("p", record.content);
      content.dir = "auto";
      article.append(content);
      board.append(article);
    });
    byId("viva-record-nav").hidden = !records.length;
    byId("viva-record-count").textContent = records.length ? `${offset + 1}–${end} of ${records.length}` : "";
    byId("viva-previous").disabled = offset === 0;
    byId("viva-next").disabled = end === records.length;
  }
  function render(result) {
    active = result;
    offset = 0;
    const verified = result.status === "verified";
    const facts = byId("viva-facts");
    facts.replaceChildren();
    const fields = [
      ["Source PDF", result.source_file], ["PDF SHA-256", result.source_sha256],
      ["Run ID", result.run_id], ["Pages with text", `${result.extracted_pages} / ${result.page_count}`],
      ["Candidate passages", result.candidate_count], ["Validated passages", result.valid_count],
      ["Rejected passages", result.rejected.length], ["Validation", "Fixed PDF passage schema"],
    ];
    if (verified) fields.push(["Database and collection", `${result.database}.${result.collection}`],
      ["Saved passages verified", result.saved_count], ["Read-back SHA-256", result.records_sha256],
      ["Saved at (UTC)", result.saved_at]);
    for (const [key, value] of fields) {
      const item = document.createElement("div");
      item.append(node("dt", key), node("dd", value));
      facts.append(item);
    }
    const warnings = byId("viva-warnings");
    warnings.replaceChildren(...[...result.warnings, ...result.rejected.map((item) =>
      `Page ${item.page_number ?? "?"}, chunk ${item.chunk_index ?? "?"}: ${item.errors.join("; ")}`)]
      .map((warning) => node("li", warning)));
    warnings.hidden = !warnings.childElementCount;
    runInput.value = result.run_id;
    save.hidden = verified;
    evidence.hidden = false;
    renderRecords();
    status.textContent = verified
      ? `MongoDB read-back verified: ${result.saved_count} saved passages.`
      : result.valid_count ? "Preview ready. Review the passages before saving. Nothing saved yet."
      : "No validated passages were extracted. Nothing can be saved.";
  }

  upload.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !file.files.length) return;
    const selected = file.files[0];
    const form = new FormData(upload);
    active = null;
    clearSource();
    evidence.hidden = true;
    setBusy(true);
    status.textContent = "Extracting and validating PDF passages…";
    try {
      const result = await api("/preview", { method: "POST", body: form });
      sourceUrl = URL.createObjectURL(new Blob([selected], { type: "application/pdf" }));
      render(result);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      setBusy(false);
    }
  });

  file.addEventListener("change", () => {
    active = null;
    clearSource();
    evidence.hidden = true;
    save.disabled = true;
    status.textContent = "";
  });
  save.addEventListener("click", async () => {
    if (busy || active?.status !== "preview" || !active.valid_count) return;
    setBusy(true);
    status.textContent = "Saving the reviewed passages, then reading them back from MongoDB…";
    try {
      render(await api(`/${encodeURIComponent(active.run_id)}/save`, { method: "POST" }));
    } catch (error) {
      status.textContent = error.message;
    } finally {
      setBusy(false);
    }
  });
  reopen.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const id = runInput.value.trim();
    setBusy(true);
    status.textContent = "Reading the saved run from MongoDB…";
    try {
      const result = await api(`/${encodeURIComponent(id)}`, { method: "GET" });
      if (id !== active?.run_id) clearSource();
      render(result);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      setBusy(false);
    }
  });
  byId("viva-previous").addEventListener("click", () => {
    offset = Math.max(0, offset - pageSize);
    renderRecords();
  });
  byId("viva-next").addEventListener("click", () => {
    offset += pageSize;
    renderRecords();
  });
})();
