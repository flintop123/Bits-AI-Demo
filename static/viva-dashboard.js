(() => {
  const byId = (id) => document.getElementById(id);
  const upload = byId("viva-upload-form");
  if (!upload) return;
  const evidence = byId("viva-evidence");
  const file = byId("viva-pdf");
  const save = byId("viva-save");
  const reactPreview = byId("viva-react-preview");
  const reactPreviewStatus = byId("viva-react-preview-status");
  const status = byId("viva-status");
  const reopen = byId("viva-reopen-form");
  const runInput = byId("viva-run-id");
  const attach = byId("viva-attach");
  const ask = byId("viva-doc-question-form");
  const questionInput = byId("viva-doc-question");
  const answerLanguage = byId("viva-doc-language");
  const proof = byId("viva-proof");
  const proofImage = byId("viva-proof-image");
  const filter = byId("viva-filter");
  const pageSize = 8;
  let active = null;
  let sourceUrl = null;
  let offset = 0;
  let busy = false;
  let proofUrl = null;
  let proofRequest = null;

  function node(tag, text) {
    const el = document.createElement(tag);
    el.textContent = text;
    return el;
  }
  function clearSource() {
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl = null;
  }
  function setStep(step) {
    document.querySelectorAll("[data-viva-step]").forEach((item) => {
      if (item.dataset.vivaStep === step) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
  }
  function setStatus(message, tone = "info") {
    status.textContent = message;
    status.dataset.tone = tone;
  }
  function setBusy(value) {
    busy = value;
    evidence.setAttribute("aria-busy", String(value));
    [...upload.elements, ...reopen.elements, ...attach.elements, ...ask.elements]
      .forEach((element) => { element.disabled = value; });
    save.disabled = value || active?.status !== "preview" || !active.valid_count;
    reactPreview.disabled = value || active?.status !== "preview" || !active.source_available;
  }
  async function api(path, options) {
    const response = await fetch(`/api/v1/viva/uploads${path}`, {
      ...options, headers: { "X-Agri-Dashboard": "1" }, cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `The request failed (HTTP ${response.status}).`);
    return payload;
  }
  function clearProof() {
    if (proofRequest) proofRequest.abort();
    proofRequest = null;
    if (proofUrl) URL.revokeObjectURL(proofUrl);
    proofUrl = null;
    proofImage.removeAttribute("src");
    proofImage.hidden = true;
    byId("viva-proof-status").removeAttribute("data-tone");
  }
  proof.addEventListener("close", clearProof);

  const anchorLabels = {
    exact_passage: "Exact passage located",
    exact_quote: "Exact answer quote located",
    exact_excerpt: "Exact excerpt located",
    verified_table_cell: "Verified table cell",
    page_only: "Source page only — no exact highlight verified",
  };
  function proofButton(path, title, sourceText, buttonText = "Inspect source") {
    const button = node("button", buttonText);
    button.type = "button";
    button.className = "secondary-button";
    button.addEventListener("click", async () => {
      clearProof();
      const controller = new AbortController();
      proofRequest = controller;
      byId("viva-proof-heading").textContent = title;
      byId("viva-proof-text").textContent = sourceText;
      const proofStatus = byId("viva-proof-status");
      proofStatus.textContent = "Opening the original page…";
      proof.showModal();
      try {
        const response = await fetch(`/api/v1/viva/uploads/${active.run_id}/${path}`, {
          headers: { "X-Agri-Dashboard": "1" }, cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) {
          const problem = await response.json().catch(() => ({}));
          if (response.status === 404 && active?.status === "verified") attach.hidden = false;
          throw new Error(problem.error || `Could not render this page (HTTP ${response.status}).`);
        }
        const kind = response.headers.get("X-Source-Anchor");
        const image = await response.blob();
        if (proofRequest !== controller) return;
        proofUrl = URL.createObjectURL(image);
        proofStatus.dataset.tone = kind in anchorLabels && kind !== "page_only" ? "success" : "info";
        proofStatus.textContent = anchorLabels[kind] || anchorLabels.page_only;
        proofImage.alt = `Original PDF source for ${title}. ${proofStatus.textContent}.`;
        proofImage.src = proofUrl;
        proofImage.hidden = false;
      } catch (error) {
        if (proofRequest === controller) {
          proofStatus.dataset.tone = "error";
          proofStatus.textContent = error.message;
        }
      }
    });
    return button;
  }

  function renderTables(tables) {
    const panel = byId("viva-table-panel");
    const container = byId("viva-tables");
    container.replaceChildren();
    panel.hidden = !tables.length;
    tables.map((table, index) => ({table, index})).sort((a, b) =>
      a.table.page_number - b.table.page_number).forEach(({table, index: tableIndex}) => {
      const group = document.createElement("details");
      group.append(node("summary", `Page ${table.page_number} · ${table.cells.length} verified cells`));
      const context = Object.values(table.context).map((entry) => `${entry.text} (p. ${entry.page})`);
      group.append(node("p", [...new Set(context)].join(" · ")));
      const scroller = document.createElement("div");
      scroller.className = "viva-table-scroll";
      const grid = document.createElement("table");
      const head = grid.createTHead().insertRow();
      ["Row", "Column", "Value", "Unit", "Source"].forEach((label) => {
        const th = node("th", label);
        th.scope = "col";
        head.append(th);
      });
      const body = grid.createTBody();
      table.cells.forEach((cell, cellIndex) => {
        const row = body.insertRow();
        [cell.row, cell.column, cell.printed_text, cell.unit].forEach((value) => {
          row.append(node("td", value));
        });
        row.insertCell().append(proofButton(`table-evidence/${tableIndex}/${cellIndex}`,
          `Page ${cell.page_number} · ${cell.row}`, `${cell.column}: ${cell.value} ${cell.unit}\nPrinted cell: ${cell.printed_text}`,
          "Highlight cell"));
      });
      scroller.append(grid);
      group.append(scroller);
      container.append(group);
    });
  }
  function renderRecords() {
    if (!active) return;
    const title = active.status === "verified" ? "Saved from MongoDB" : "Validated preview";
    const normalized = (value) => value.normalize("NFC").toLowerCase().replace(/\s+/g, " ").trim();
    const term = normalized(filter.value);
    const records = (active.records || []).filter((record) => normalized(record.content).includes(term));
    const end = Math.min(offset + pageSize, records.length);
    const board = byId("viva-records");
    board.replaceChildren();
    if (term && !records.length) board.append(node("p", "No extracted passages match that text."));
    records.slice(offset, end).forEach((record) => {
      const article = document.createElement("article");
      article.className = "viva-record";
      article.append(node("h3", `Page ${record.page_number} · Chunk ${record.chunk_index}`));
      const anchor = record.source_anchor;
      const precision = anchorLabels[anchor?.kind] || "Stored page and chunk";
      article.append(node("small", `${title} · ${record.extraction_method} · ${record.language} · ${precision}`));
      const actions = document.createElement("div");
      actions.className = "viva-card-actions";
      actions.append(proofButton(`evidence/${record.page_number}/${record.chunk_index}`,
        `Page ${record.page_number} · Chunk ${record.chunk_index}`,
        anchor?.quote ? `Matched excerpt:\n${anchor.quote}\n\nExtracted passage:\n${record.content}` : record.content));
      if (sourceUrl) {
        const link = node("a", "Open source page");
        link.href = `${sourceUrl}#page=${Number(record.page_number)}`;
        link.target = "_blank";
        link.rel = "noopener";
        actions.append(link);
      }
      const content = node("p", record.content);
      content.dir = "auto";
      article.append(content);
      article.append(actions);
      board.append(article);
    });
    byId("viva-record-nav").hidden = !records.length;
    byId("viva-record-count").textContent = records.length
      ? `${offset + 1}–${end} of ${records.length}${term ? " matching" : ""}` : "";
    byId("viva-previous").disabled = offset === 0;
    byId("viva-next").disabled = end === records.length;
  }
  function render(result) {
    const differentRun = active?.run_id !== result.run_id;
    if (differentRun) {
      filter.value = "";
      questionInput.value = "";
      answerLanguage.value = "auto";
      byId("viva-audit").open = false;
    }
    active = result;
    offset = 0;
    const verified = result.status === "verified";
    const facts = byId("viva-facts");
    const audit = byId("viva-audit-facts");
    facts.replaceChildren();
    audit.replaceChildren();
    const tables = result.tables || [];
    const cellCount = tables.reduce((count, table) => count + table.cells.length, 0);
    const fields = [
      ["Source PDF", result.source_file],
      ["Pages with text", `${result.extracted_pages} / ${result.page_count}`],
      [verified ? "Saved passages verified" : "Validated passages", verified ? result.saved_count : result.valid_count],
      ["Verified table cells", cellCount],
    ];
    const anchored = result.records.filter((row) =>
      ["exact_passage", "exact_excerpt"].includes(row.source_anchor?.kind)).length;
    const details = [
      ["Run ID", result.run_id], ["PDF SHA-256", result.source_sha256],
      ["Candidate passages", result.candidate_count], ["Rejected passages", result.rejected.length],
      ["Validation", "Fixed PDF passage schema"],
      ["Passages with a verified highlight", `${anchored} / ${result.records.length}`],
    ];
    if (verified) details.push(["Database and collection", `${result.database}.${result.collection}`],
      ["Read-back SHA-256", result.records_sha256], ["Saved at (UTC)", result.saved_at]);
    if (verified && tables.length) details.push(["Table evidence SHA-256", result.tables_sha256]);
    for (const [target, entries] of [[facts, fields], [audit, details]]) {
      for (const [key, value] of entries) {
        const item = document.createElement("div");
        if (key.endsWith("SHA-256") || key === "Run ID") item.className = "viva-audit-code";
        item.append(node("dt", key), node("dd", value));
        target.append(item);
      }
    }
    const warnings = byId("viva-warnings");
    warnings.replaceChildren(...[...result.warnings, ...result.rejected.map((item) =>
      `Page ${item.page_number ?? "?"}, chunk ${item.chunk_index ?? "?"}: ${item.errors.join("; ")}`)]
      .map((warning) => node("li", warning)));
    warnings.hidden = !warnings.childElementCount;
    runInput.value = result.run_id;
    save.hidden = verified;
    reactPreview.hidden = verified;
    reactPreviewStatus.textContent = "";
    reactPreviewStatus.removeAttribute("data-tone");
    byId("viva-export").hidden = !verified;
    byId("viva-doc-qa").hidden = !verified;
    byId("viva-examples").hidden = !tables.some((table) => table.profile === "bihar_des_final_2024_25_crop_page3");
    byId("viva-doc-qa-status").textContent = "";
    byId("viva-doc-qa-status").removeAttribute("data-tone");
    byId("viva-doc-qa-status").removeAttribute("lang");
    byId("viva-doc-citations").replaceChildren();
    attach.hidden = !verified || result.source_available;
    renderTables(tables);
    byId("viva-passage-filter").hidden = !result.records.length;
    evidence.hidden = false;
    renderRecords();
    setStep(verified ? "verified" : "review");
    setStatus(verified
      ? result.already_saved
        ? `This PDF was already saved. Reused its verified run; nothing was added.${result.preview_matches_saved_passages ? "" : " Showing the earlier saved extraction, not replacing it."}`
        : `MongoDB read-back verified: ${result.saved_count} saved passages.`
      : result.valid_count ? "Preview ready. Review the passages before saving. Nothing saved yet."
      : "No validated passages were extracted. Nothing can be saved.", verified ? "success" : "info");
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
    setStatus("Extracting and validating PDF passages…");
    try {
      const result = await api("/preview", { method: "POST", body: form });
      sourceUrl = URL.createObjectURL(new Blob([selected], { type: "application/pdf" }));
      render(result);
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      setBusy(false);
    }
  });

  file.addEventListener("change", () => {
    active = null;
    clearSource();
    evidence.hidden = true;
    save.disabled = true;
    setStep("upload");
    setStatus("");
  });
  reactPreview.addEventListener("click", async () => {
    if (busy || active?.status !== "preview" || !active.source_available) return;
    setBusy(true);
    reactPreviewStatus.textContent = "Running ReAct on the staged PDF in dry-run mode…";
    reactPreviewStatus.removeAttribute("data-tone");
    try {
      const observed = await api(`/${encodeURIComponent(active.run_id)}/react-preview`, { method: "POST" });
      if (!observed.react?.tool_called || !observed.dry_run || observed.database_writes !== false
          || observed.source_sha256 !== active.source_sha256) {
        throw new Error("The preview did not confirm a dry run of this PDF.");
      }
      reactPreviewStatus.textContent = `Called ${observed.react.tool}. The document agent extracted ${observed.pages_extracted} of ${observed.pages_requested} pages (${observed.ocr_pages} OCR) and ${observed.chunks_processed} passages. Nothing saved.`;
      reactPreviewStatus.dataset.tone = "success";
    } catch (error) {
      reactPreviewStatus.textContent = error.message;
      reactPreviewStatus.dataset.tone = "error";
    } finally {
      setBusy(false);
    }
  });
  save.addEventListener("click", async () => {
    if (busy || active?.status !== "preview" || !active.valid_count) return;
    setBusy(true);
    setStatus("Saving the reviewed passages, then reading them back from MongoDB…");
    try {
      render(await api(`/${encodeURIComponent(active.run_id)}/save`, { method: "POST" }));
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      setBusy(false);
    }
  });
  reopen.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const id = runInput.value.trim();
    setBusy(true);
    setStatus("Reading the saved run from MongoDB…");
    try {
      const result = await api(`/${encodeURIComponent(id)}`, { method: "GET" });
      if (id !== active?.run_id) clearSource();
      render(result);
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      setBusy(false);
    }
  });
  attach.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || active?.status !== "verified") return;
    const original = byId("viva-original").files[0];
    if (!original) return;
    const form = new FormData(attach);
    setBusy(true);
    setStatus("Checking the original PDF fingerprint…");
    try {
      const result = await api(`/${active.run_id}/attach`, {method: "POST", body: form});
      clearSource();
      sourceUrl = URL.createObjectURL(new Blob([original], {type: "application/pdf"}));
      render(result);
      setStatus("Original PDF matched. Source pages are ready to inspect.", "success");
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      setBusy(false);
    }
  });
  byId("viva-examples").addEventListener("click", (event) => {
    const example = event.target.closest("button[data-viva-question]");
    if (!example || busy) return;
    questionInput.value = example.dataset.vivaQuestion;
    answerLanguage.value = example.dataset.language;
    questionInput.focus();
  });
  function renderTableAnswer(result) {
    const answer = document.createElement("article");
    answer.className = "viva-table-answer";
    answer.lang = result.answer_language;
    const hindi = result.answer_language === "hi";
    const label = node("p", hindi ? "सत्यापित तालिका" : "Verified table answer");
    label.className = "viva-answer-label";
    answer.append(label, node("h4", result.heading));
    if (result.estimate) answer.append(node("p", result.estimate));
    const facts = document.createElement("div");
    facts.className = "viva-answer-facts";
    for (const item of result.table_cells) {
      const fact = document.createElement("div");
      const value = node("strong", item.display_value);
      const numeric = document.createElement("div");
      numeric.className = "viva-answer-number";
      numeric.append(value, node("span", item.display_unit));
      const page = node("small", hindi ? `पृष्ठ ${item.page_number}` : `Page ${item.page_number}`);
      const actions = document.createElement("div");
      actions.className = "viva-card-actions";
      actions.append(page, proofButton(`table-evidence/${item.table_index}/${item.cell_index}`,
        `Page ${item.page_number} · ${item.row}`,
        `${item.column}: ${item.printed_text} ${item.unit}`,
        hindi ? "मूल सेल देखें" : "View exact source cell"));
      fact.append(node("h5", item.label), numeric, actions);
      facts.append(fact);
    }
    answer.append(facts);
    return answer;
  }
  ask.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || active?.status !== "verified") return;
    const question = questionInput.value.trim();
    if (!question) return;
    setBusy(true);
    const message = byId("viva-doc-qa-status");
    const citations = byId("viva-doc-citations");
    citations.replaceChildren();
    message.removeAttribute("data-tone");
    message.removeAttribute("lang");
    message.textContent = "Searching only this saved PDF…";
    try {
      const response = await fetch(`/api/v1/viva/uploads/${active.run_id}/ask`, {
        method: "POST", headers: {"X-Agri-Dashboard": "1", "Content-Type": "application/json"},
        body: JSON.stringify({question, answer_language: answerLanguage.value}), cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not answer from this PDF.");
      message.textContent = result.message;
      message.dataset.tone = result.status === "answered" ? "success" : "info";
      if (result.answer_language) message.lang = result.answer_language;
      if (result.table_cells?.length) citations.append(renderTableAnswer(result));
      for (const item of (result.citations || [])) {
        const card = document.createElement("article");
        card.className = "viva-record";
        const title = `Page ${item.page_number} · Chunk ${item.chunk_index}`;
        card.append(node("h3", title));
        const quote = node("p", item.quote || item.content);
        quote.dir = "auto";
        const path = `evidence/${item.page_number}/${item.chunk_index}` +
          (item.quote ? `?quote=${encodeURIComponent(item.quote)}` : "");
        const actions = document.createElement("div");
        actions.className = "viva-card-actions";
        actions.append(proofButton(path, title,
          item.quote ? `Answer quote:\n${item.quote}\n\nFull passage:\n${item.content}` : item.content));
        card.append(quote, actions);
        citations.append(card);
      }
    } catch (error) {
      message.dataset.tone = "error";
      message.textContent = error.message;
    } finally {
      setBusy(false);
    }
  });
  byId("viva-export").addEventListener("click", () => {
    if (active?.status !== "verified") return;
    const {source_available, ...record} = active;
    const blob = new Blob([JSON.stringify(record, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `agriagent-verified-${active.run_id}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  byId("viva-previous").addEventListener("click", () => {
    offset = Math.max(0, offset - pageSize);
    renderRecords();
  });
  byId("viva-next").addEventListener("click", () => {
    offset += pageSize;
    renderRecords();
  });
  filter.addEventListener("input", () => {
    offset = 0;
    renderRecords();
  });
})();
