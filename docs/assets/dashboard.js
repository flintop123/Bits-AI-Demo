"use strict";

const state = { data: null, language: "en", days: 90 };
const qaState = {
  mode: "checking",
  apiBase: "http://127.0.0.1:5000",
  selectedExample: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function text(en, hi) {
  return state.language === "hi" ? hi : en;
}

function number(value, maximumFractionDigits = 0) {
  return new Intl.NumberFormat(state.language === "hi" ? "hi-IN" : "en-IN", {
    maximumFractionDigits,
  }).format(value);
}

function dateLabel(value, options = {}) {
  return new Intl.DateTimeFormat(state.language === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: options.year ? "numeric" : undefined,
  }).format(new Date(`${value}T00:00:00Z`));
}

function setLanguage(language) {
  state.language = language;
  document.documentElement.lang = language;
  $$('[data-en][data-hi]').forEach((node) => {
    node.textContent = node.dataset[language];
  });
  $$('[data-placeholder-en][data-placeholder-hi]').forEach((node) => {
    node.placeholder = node.dataset[`placeholder${language === "hi" ? "Hi" : "En"}`];
  });
  $$(".language-option").forEach((button) => {
    const active = button.dataset.language === language;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (state.data) {
    renderAll();
    if (qaState.selectedExample != null) {
      const example = state.data.verified_examples[qaState.selectedExample];
      $("#question-input").value = language === "hi" ? example.question_hi : example.question_en;
      $("#question-count").textContent = $("#question-input").value.length;
    }
  }
}

function qaModeText() {
  if (qaState.mode === "live") return text("Live local QA connected", "लाइव स्थानीय प्रश्नोत्तर जुड़ा है");
  if (qaState.mode === "snapshot") return text("Hosted evidence snapshot", "होस्टेड साक्ष्य स्नैपशॉट");
  return text("Checking local QA service…", "स्थानीय प्रश्नोत्तर सेवा की जांच…");
}

function updateQaMode() {
  const indicator = $("#qa-mode-indicator");
  indicator.classList.toggle("is-live", qaState.mode === "live");
  indicator.classList.toggle("is-snapshot", qaState.mode === "snapshot");
  $("#qa-mode-label").textContent = qaModeText();
  $("#qa-privacy-note").textContent = qaState.mode === "live"
    ? text("Question sent only to your local AgriAgent service.", "प्रश्न केवल आपकी स्थानीय AgriAgent सेवा को भेजा जाता है।")
    : text("Hosted mode answers the verified questions below.", "होस्टेड मोड नीचे दिए सत्यापित प्रश्नों का उत्तर देता है।");
}

function hideAnswerStates() {
  ["#answer-placeholder", "#answer-loading", "#answer-result", "#answer-error"].forEach((selector) => {
    $(selector).hidden = true;
  });
}

function setAnswerLoading() {
  hideAnswerStates();
  $("#answer-loading").hidden = false;
  $("#ask-button").disabled = true;
}

function sourceText(source) {
  const title = source.title || source.source_file || source.source || source.source_id || source.source_url || text("Retrieved source", "पुनर्प्राप्त स्रोत");
  const page = source.page_number || source.page;
  return page ? `${title} · ${text("page", "पृष्ठ")} ${page}` : String(title);
}

function showQaAnswer(payload, mode) {
  hideAnswerStates();
  $("#answer-result").hidden = false;
  $("#answer-copy").textContent = payload.answer;
  $("#answer-mode-badge").textContent = mode === "live" ? text("Live local answer", "लाइव स्थानीय उत्तर") : text("Verified snapshot", "सत्यापित स्नैपशॉट");
  $("#answer-intent-badge").textContent = payload.intent || text("grounded QA", "स्रोत-आधारित प्रश्नोत्तर");
  const sources = payload.sources || [];
  const container = $("#answer-sources");
  container.replaceChildren();
  if (sources.length) {
    const heading = document.createElement("strong");
    heading.textContent = text("Sources", "स्रोत");
    const list = document.createElement("ul");
    sources.slice(0, 5).forEach((source) => {
      const item = document.createElement("li");
      item.textContent = sourceText(source);
      list.append(item);
    });
    container.append(heading, list);
  }
  $("#ask-button").disabled = false;
}

function showQaError(message) {
  hideAnswerStates();
  $("#answer-error").hidden = false;
  $("#answer-error-copy").textContent = message;
  $("#ask-button").disabled = false;
}

function selectedVerifiedExample(question) {
  if (qaState.selectedExample == null) return null;
  const example = state.data.verified_examples[qaState.selectedExample];
  const expected = state.language === "hi" ? example.question_hi : example.question_en;
  return question.trim() === expected.trim() ? example : null;
}

function snapshotAnswer(example, requestedLanguage) {
  const hindi = requestedLanguage === "hi" || (requestedLanguage === "auto" && /[\u0900-\u097F]/.test($("#question-input").value));
  return {
    answer: hindi ? example.answer_hi : example.answer_en,
    intent: text("verified example", "सत्यापित उदाहरण"),
    sources: [{ title: example.source }],
  };
}

async function detectLocalQa() {
  const localPage = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (!localPage) {
    qaState.mode = "snapshot";
    updateQaMode();
    return;
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 1800);
  try {
    const response = await fetch(`${qaState.apiBase}/health`, { signal: controller.signal });
    qaState.mode = response.ok ? "live" : "snapshot";
  } catch (_error) {
    qaState.mode = "snapshot";
  } finally {
    window.clearTimeout(timeout);
    updateQaMode();
  }
}

async function submitQuestion(event) {
  event.preventDefault();
  const question = $("#question-input").value.trim();
  if (!question) return;
  const answerLanguage = $("#answer-language").value;
  const verified = selectedVerifiedExample(question);
  setAnswerLoading();

  if (qaState.mode !== "live") {
    if (verified) {
      showQaAnswer(snapshotAnswer(verified, answerLanguage), "snapshot");
    } else {
      showQaError(text(
        "GitHub Pages cannot run MongoDB or Qwen3. Choose a verified question here, or start the local API for unrestricted grounded QA.",
        "GitHub Pages MongoDB या Qwen3 नहीं चला सकता। यहां सत्यापित प्रश्न चुनें, या स्वतंत्र स्रोत-आधारित प्रश्नोत्तर के लिए स्थानीय API शुरू करें।",
      ));
    }
    return;
  }

  try {
    const response = await fetch(`${qaState.apiBase}/api/v1/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer_language: answerLanguage }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || text("The request failed.", "अनुरोध विफल हुआ।"));
    showQaAnswer(payload, "live");
  } catch (error) {
    qaState.mode = "snapshot";
    updateQaMode();
    if (verified) {
      showQaAnswer(snapshotAnswer(verified, answerLanguage), "snapshot");
    } else {
      showQaError(error.message || text("The local QA service could not be reached.", "स्थानीय प्रश्नोत्तर सेवा उपलब्ध नहीं है।"));
    }
  }
}

function linePath(points) {
  return points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
}

function renderIngestionChart() {
  const all = state.data.daily_records;
  const series = all.slice(-state.days);
  const width = 900;
  const height = 310;
  const padding = { top: 20, right: 18, bottom: 38, left: 48 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const max = Math.max(...series.map((item) => item.records));
  const min = 0;
  const x = (index) => padding.left + (index / Math.max(1, series.length - 1)) * innerWidth;
  const y = (value) => padding.top + innerHeight - ((value - min) / Math.max(1, max - min)) * innerHeight;
  const points = series.map((item, index) => ({ x: x(index), y: y(item.records), ...item }));
  const path = linePath(points);
  const areaPath = `${path} L${points.at(-1).x},${padding.top + innerHeight} L${points[0].x},${padding.top + innerHeight} Z`;
  const yTicks = [0, .25, .5, .75, 1].map((ratio) => Math.round(max * ratio));
  const xTickIndexes = [0, Math.floor((series.length - 1) / 3), Math.floor((series.length - 1) * 2 / 3), series.length - 1];

  $("#ingestion-chart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <defs><linearGradient id="ingestion-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1f5a43" stop-opacity=".28"/><stop offset="1" stop-color="#1f5a43" stop-opacity=".02"/></linearGradient></defs>
      ${yTicks.map((tick) => `<line class="grid-line" x1="${padding.left}" y1="${y(tick)}" x2="${width - padding.right}" y2="${y(tick)}"/><text x="${padding.left - 10}" y="${y(tick) + 4}" text-anchor="end">${number(tick)}</text>`).join("")}
      <path class="area" d="${areaPath}"/>
      <path class="line" d="${path}"/>
      ${points.filter((_, index) => index === 0 || index === points.length - 1 || index % Math.ceil(points.length / 12) === 0).map((point) => `<circle class="point" cx="${point.x}" cy="${point.y}" r="4"><title>${dateLabel(point.date, { year: true })}: ${number(point.records)} ${text("records", "रिकॉर्ड")}</title></circle>`).join("")}
      ${xTickIndexes.map((index) => `<text x="${x(index)}" y="${height - 8}" text-anchor="${index === 0 ? "start" : index === series.length - 1 ? "end" : "middle"}">${dateLabel(series[index].date)}</text>`).join("")}
    </svg>`;

  const total = series.reduce((sum, item) => sum + item.records, 0);
  $("#window-total").textContent = number(total);
  $("#date-range").textContent = `${dateLabel(series[0].date, { year: true })} — ${dateLabel(series.at(-1).date, { year: true })}`;
}

function convexHull(points) {
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  if (sorted.length <= 2) return sorted;
  const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), point) <= 0) lower.pop();
    lower.push(point);
  }
  const upper = [];
  for (const point of sorted.reverse()) {
    while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), point) <= 0) upper.pop();
    upper.push(point);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

function renderMap() {
  const locations = state.data.locations;
  const width = 940;
  const height = 540;
  const pad = 48;
  const longitudes = locations.map((item) => item.longitude);
  const latitudes = locations.map((item) => item.latitude);
  const bounds = {
    minLon: Math.min(...longitudes) - .25,
    maxLon: Math.max(...longitudes) + .25,
    minLat: Math.min(...latitudes) - .2,
    maxLat: Math.max(...latitudes) + .2,
  };
  const x = (lon) => pad + ((lon - bounds.minLon) / (bounds.maxLon - bounds.minLon)) * (width - pad * 2);
  const y = (lat) => height - pad - ((lat - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * (height - pad * 2);
  const points = locations.map((item) => ({ ...item, x: x(item.longitude), y: y(item.latitude) }));
  const hull = convexHull(points);
  const center = hull.reduce((acc, item) => ({ x: acc.x + item.x / hull.length, y: acc.y + item.y / hull.length }), { x: 0, y: 0 });
  const expandedHull = hull.map((point) => ({ x: center.x + (point.x - center.x) * 1.08, y: center.y + (point.y - center.y) * 1.08 }));
  const tooltip = $("#map-tooltip");

  $("#market-map").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      ${[.2,.4,.6,.8].map((ratio) => `<line class="longitude" x1="${pad + ratio * (width-pad*2)}" y1="${pad}" x2="${pad + ratio * (width-pad*2)}" y2="${height-pad}"/><line class="latitude" x1="${pad}" y1="${pad + ratio * (height-pad*2)}" x2="${width-pad}" y2="${pad + ratio * (height-pad*2)}"/>`).join("")}
      <path class="region" d="${expandedHull.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")} Z"/>
      ${points.map((point, index) => `<circle class="market-point" tabindex="0" data-index="${index}" cx="${point.x}" cy="${point.y}" r="5"><title>${point.market}, ${point.district}</title></circle>`).join("")}
    </svg>`;

  $$(".market-point", $("#market-map")).forEach((node) => {
    const show = () => {
      const item = points[Number(node.dataset.index)];
      const card = $(".map-card").getBoundingClientRect();
      const dot = node.getBoundingClientRect();
      tooltip.innerHTML = `<strong>${item.market}</strong><span>${item.district}<br>${item.latitude.toFixed(4)}, ${item.longitude.toFixed(4)}<br>${text("Confidence", "विश्वास")}: ${number(item.confidence * 100, 1)}%</span>`;
      tooltip.hidden = false;
      const left = Math.min(card.width - 285, Math.max(12, dot.left - card.left + 12));
      const top = Math.max(12, dot.top - card.top - 84);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    };
    node.addEventListener("mouseenter", show);
    node.addEventListener("focus", show);
    node.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    node.addEventListener("blur", () => { tooltip.hidden = true; });
  });
}

function renderMarketRanking() {
  const items = state.data.potato_intelligence.market_sample;
  const max = Math.max(...items.map((item) => item.latest_average_price));
  $("#market-ranking-list").innerHTML = items.map((item, index) => `
    <div class="rank-row">
      <span class="rank-index">${number(index + 1)}</span>
      <div class="rank-name"><strong>${state.language === "hi" ? item.market : item.market_label}</strong><span>${state.language === "hi" ? item.district : item.district_label}</span></div>
      <div class="rank-bar"><i style="width:${(item.latest_average_price / max * 100).toFixed(1)}%"></i></div>
      <span class="rank-price">₹${number(item.latest_average_price)}</span>
    </div>`).join("");
}

function renderAgents() {
  $("#agent-grid").innerHTML = state.data.agents.map((agent, index) => `
    <article class="agent-card">
      <span class="agent-number">0${index + 1}</span>
      <h3>${state.language === "hi" ? agent.name_hi : agent.name}</h3>
      <p>${state.language === "hi" ? agent.role_hi : agent.role}</p>
      <small>${agent.tool}</small>
    </article>`).join("");
}

function renderExamples() {
  $("#qa-examples").innerHTML = state.data.verified_examples.map((item) => `
    <article class="qa-card">
      <span class="question-mark">?</span>
      <h3>${state.language === "hi" ? item.question_hi : item.question_en}</h3>
      <p>${state.language === "hi" ? item.answer_hi : item.answer_en}</p>
      <small>${text("Source", "स्रोत")}: ${item.source}</small>
    </article>`).join("");
}

function renderVerifiedPrompts() {
  const container = $("#verified-prompts");
  container.replaceChildren();
  state.data.verified_examples.forEach((example, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "prompt-button";
    button.textContent = state.language === "hi" ? example.question_hi : example.question_en;
    button.addEventListener("click", () => {
      qaState.selectedExample = index;
      $("#question-input").value = button.textContent;
      $("#question-count").textContent = button.textContent.length;
      $("#question-input").focus();
    });
    container.append(button);
  });
}

function renderEvaluation() {
  const evaluation = state.data.evaluation;
  const cards = [
    [text("PROTOCOL CASES", "प्रोटोकॉल मामले"), `${evaluation.protocol_cases.passed}/${evaluation.protocol_cases.total}`, text("deterministic checks passed", "निर्धारित जांच उत्तीर्ण")],
    [text("AUTOMATED TESTS", "स्वचालित परीक्षण"), `${evaluation.automated_tests.passed}/${evaluation.automated_tests.total}`, text("repository test suite", "रिपॉजिटरी परीक्षण सूट")],
    [text("REHEARSAL", "पूर्वाभ्यास"), `${evaluation.rehearsal_checks.passed}/${evaluation.rehearsal_checks.total}`, text("evaluator-style checks", "मूल्यांकन-शैली जांच")],
    [text("DATABASE DUMP", "डेटाबेस डंप"), number(evaluation.database_records_validated), text("portable records validated", "पोर्टेबल रिकॉर्ड सत्यापित")],
  ];
  $("#evaluation-grid").innerHTML = cards.map(([label, value, note]) => `<article class="evaluation-card"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`).join("");
}

function renderTeam() {
  $("#team-list").innerHTML = state.data.team.map((member, index) => `
    <div class="team-member"><span>${index + 1}</span><strong>${member.name}</strong><small>${member.roll}</small></div>`).join("");
}

function renderAll() {
  const { totals, quality, potato_intelligence: potato, retrieval, geospatial } = state.data;

  $$('[data-metric]').forEach((node) => { node.textContent = number(totals[node.dataset.metric]); });
  const qualityValues = [
    ["price", quality.price_completeness_percent],
    ["provenance", quality.provenance_completeness_percent],
    ["coordinate", quality.coordinate_verification_percent],
  ];
  qualityValues.forEach(([key, value]) => {
    $(`#${key}-quality`).textContent = `${number(value, 1)}%`;
    $(`#${key}-bar`).style.width = `${value}%`;
  });

  $("#verified-count").textContent = number(geospatial.verified);
  $("#coverage-percent").textContent = `${number(totals.geospatial_coverage_percent, 1)}%`;
  $("#potato-latest").textContent = `₹${number(potato.summary.latest_average_price)}`;
  $("#potato-change").textContent = `+${number(potato.summary.change_percent, 2)}%`;
  $("#potato-observations").textContent = number(potato.summary.observations);
  $("#potato-markets").textContent = number(potato.summary.markets);
  $("#potato-volatility").textContent = `${number(potato.summary.daily_volatility_percent, 1)}%`;
  $("#potato-anomalies").textContent = number(potato.summary.anomaly_days);

  const keyword = retrieval.keyword_hit_rate_at_k * 100;
  const hybrid = retrieval.hybrid_hit_rate_at_k * 100;
  $("#keyword-hit").textContent = `${number(keyword, 1)}%`;
  $("#hybrid-hit").textContent = `${number(hybrid, 1)}%`;
  $("#keyword-track").style.width = `${keyword}%`;
  $("#hybrid-track").style.width = `${hybrid}%`;
  $("#snapshot-date").textContent = dateLabel(state.data.meta.latest_data_date, { year: true });

  renderIngestionChart();
  renderMap();
  renderMarketRanking();
  renderAgents();
  renderExamples();
  renderVerifiedPrompts();
  renderEvaluation();
  renderTeam();
  updateQaMode();
}

async function initialize() {
  $$(".language-option").forEach((button) => button.addEventListener("click", () => setLanguage(button.dataset.language)));
  $$("[data-days]").forEach((button) => button.addEventListener("click", () => {
    state.days = Number(button.dataset.days);
    $$("[data-days]").forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
    renderIngestionChart();
  }));
  $("#ask-form").addEventListener("submit", submitQuestion);
  $("#question-input").addEventListener("input", () => {
    qaState.selectedExample = null;
    $("#question-count").textContent = $("#question-input").value.length;
  });

  try {
    const response = await fetch("./data/dashboard_snapshot.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    renderAll();
    await detectLocalQa();
  } catch (error) {
    console.error(error);
    $("#load-error").hidden = false;
  }
}

initialize();
