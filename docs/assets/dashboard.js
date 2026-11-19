"use strict";

const state = {
  data: null,
  language: "en",
  days: 90,
  reportingFrequency: "daily",
  districtFrequency: "daily",
  district: null,
};
let marketMap = null;
let marketMarkerLayer = null;
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
  const available = state.data.reporting_series || {};
  const fallback = state.data.daily_records.map((item) => ({
    ...item, period_start: item.date, frequency: "daily",
  }));
  const all = available[state.reportingFrequency] || fallback;
  const series = state.reportingFrequency === "daily"
    ? all.slice(-state.days)
    : all;
  if (!series.length) return;
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
      ${points.filter((_, index) => index === 0 || index === points.length - 1 || index % Math.max(1, Math.ceil(points.length / 12)) === 0).map((point) => `<circle class="point" cx="${point.x}" cy="${point.y}" r="4"><title>${dateLabel(point.period_start, { year: true })}: ${number(point.records)} ${text("records", "रिकॉर्ड")}</title></circle>`).join("")}
      ${[...new Set(xTickIndexes)].map((index) => `<text x="${x(index)}" y="${height - 8}" text-anchor="${index === 0 ? "start" : index === series.length - 1 ? "end" : "middle"}">${dateLabel(series[index].period_start)}</text>`).join("")}
    </svg>`;

  const total = series.reduce((sum, item) => sum + item.records, 0);
  $("#window-total").textContent = number(total);
  $("#date-range").textContent = `${dateLabel(series[0].period_start, { year: true })} — ${dateLabel(series.at(-1).period_start, { year: true })}`;
  $("#reporting-frequency-label").textContent = `${state.reportingFrequency.toUpperCase()} ${text("REPORT", "रिपोर्ट")}`;
}

function renderMap() {
  const locations = state.data.locations;
  const container = $("#market-map");
  if (!window.L) {
    container.textContent = text("OpenStreetMap could not be loaded.", "OpenStreetMap लोड नहीं हो सका।");
    container.classList.add("map-unavailable");
    return;
  }
  if (!marketMap) {
    marketMap = L.map(container, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(marketMap);
    marketMarkerLayer = L.layerGroup().addTo(marketMap);
  }
  marketMarkerLayer.clearLayers();
  const bounds = [];
  locations.forEach((item) => {
    const point = [item.latitude, item.longitude];
    bounds.push(point);
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    const detail = document.createElement("span");
    title.textContent = item.market;
    detail.textContent = `${item.district} · ${item.latitude.toFixed(4)}, ${item.longitude.toFixed(4)} · ${text("confidence", "विश्वास")} ${number(item.confidence * 100, 1)}%`;
    popup.append(title, document.createElement("br"), detail);
    L.circleMarker(point, {
      radius: 6, color: "#fffdf8", weight: 2, fillColor: "#d97927", fillOpacity: .92,
    }).bindPopup(popup).addTo(marketMarkerLayer);
  });
  if (bounds.length) marketMap.fitBounds(bounds, { padding: [28, 28] });
  window.setTimeout(() => marketMap.invalidateSize(), 0);
}

function renderDistrictTrend() {
  const snapshot = state.data.district_trends;
  if (!snapshot || !snapshot.districts.length) return;
  const district = state.district || snapshot.districts[0];
  state.district = district;
  const all = snapshot.frequencies[state.districtFrequency] || [];
  const limit = { daily: 30, weekly: 16, monthly: 12 }[state.districtFrequency];
  const series = all.filter((item) => item.district === district).slice(-limit);
  const chart = $("#district-trend-chart");
  if (!series.length) {
    chart.textContent = text("No observations for this selection.", "इस चयन के लिए कोई अवलोकन नहीं है।");
    return;
  }
  const width = 900;
  const height = 300;
  const pad = { top: 22, right: 18, bottom: 42, left: 66 };
  const prices = series.map((item) => item.average_modal_price);
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const range = Math.max(1, maximum - minimum);
  const x = (index) => pad.left + index / Math.max(1, series.length - 1) * (width - pad.left - pad.right);
  const y = (value) => pad.top + (maximum - value) / range * (height - pad.top - pad.bottom);
  const points = series.map((item, index) => ({ ...item, x: x(index), y: y(item.average_modal_price) }));
  const ticks = [minimum, minimum + range / 2, maximum];
  chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
    ${ticks.map((tick) => `<line class="grid-line" x1="${pad.left}" y1="${y(tick)}" x2="${width - pad.right}" y2="${y(tick)}"/><text x="${pad.left - 10}" y="${y(tick) + 4}" text-anchor="end">₹${number(tick)}</text>`).join("")}
    <path class="line district-line" d="${linePath(points)}"/>
    ${points.map((point) => `<circle class="point" cx="${point.x}" cy="${point.y}" r="4"><title>${dateLabel(point.period_start, { year: true })}: ₹${number(point.average_modal_price, 2)} (${number(point.observation_count)} observations)</title></circle>`).join("")}
    <text x="${pad.left}" y="${height - 10}">${dateLabel(series[0].period_start)}</text>
    <text x="${width - pad.right}" y="${height - 10}" text-anchor="end">${dateLabel(series.at(-1).period_start)}</text>
  </svg>`;
  $("#district-trend-title").textContent = `${district} · ${snapshot.crop} · ₹ / ${snapshot.unit}`;
  $("#district-observations").textContent = number(series.reduce((sum, item) => sum + item.observation_count, 0));
  $("#district-frequency-label").textContent = `${state.districtFrequency.toUpperCase()} ${text("DISTRICT VIEW", "जिला दृश्य")}`;
  $("#district-method").textContent = `${snapshot.method} · ${snapshot.source}`;
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
  renderDistrictTrend();
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
  $$("[data-reporting-frequency]").forEach((button) => button.addEventListener("click", () => {
    state.reportingFrequency = button.dataset.reportingFrequency;
    $$("[data-reporting-frequency]").forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
    $(".window-control").classList.toggle("is-disabled", state.reportingFrequency !== "daily");
    renderIngestionChart();
  }));
  $$("[data-district-frequency]").forEach((button) => button.addEventListener("click", () => {
    state.districtFrequency = button.dataset.districtFrequency;
    $$("[data-district-frequency]").forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
    renderDistrictTrend();
  }));
  $("#district-select").addEventListener("change", (event) => {
    state.district = event.target.value;
    renderDistrictTrend();
  });
  $("#ask-form").addEventListener("submit", submitQuestion);
  $("#question-input").addEventListener("input", () => {
    qaState.selectedExample = null;
    $("#question-count").textContent = $("#question-input").value.length;
  });

  try {
    const response = await fetch("./data/dashboard_snapshot.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    const districts = state.data.district_trends?.districts || [];
    $("#district-select").replaceChildren(...districts.map((district) => {
      const option = document.createElement("option");
      option.value = district;
      option.textContent = district;
      return option;
    }));
    state.district = districts[0] || null;
    renderAll();
    await detectLocalQa();
  } catch (error) {
    console.error(error);
    $("#load-error").hidden = false;
  }
}

initialize();
