const form = document.querySelector("#question-form");
const questionInput = document.querySelector("#question");
const askButton = document.querySelector("#ask-button");
const answerLanguage = document.querySelector("#answer-language");
const resultSection = document.querySelector("#result-section");
const loadingState = document.querySelector("#loading-state");
const errorState = document.querySelector("#error-state");
const answerState = document.querySelector("#answer-state");

const formatNumber = (value) => new Intl.NumberFormat("en-IN").format(value || 0);
const humanize = (value) => String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

function textElement(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value == null ? "—" : String(value);
  return element;
}

const intelligenceCrop = document.querySelector("#intelligence-crop");
const intelligenceCatalogLanguage = document.querySelector("#intelligence-catalog-language");
const intelligenceDistrict = document.querySelector("#intelligence-district");
const intelligenceMarket = document.querySelector("#intelligence-market");
let intelligenceCatalog = null;
let lastIntelligenceData = null;

function localizedCatalogLabel(item, language) {
  return item.labels?.[language] || item.label || item.value;
}

function catalogLookup(field, value) {
  if (!value || !intelligenceCatalog) return value;
  const language = intelligenceCatalogLanguage.value;
  const options = intelligenceCatalog[field] || [];
  const item = options.find((option) => option.value === value);
  return item ? localizedCatalogLabel(item, language) : value;
}

function populateCatalogSelect(select, items, placeholders) {
  const language = intelligenceCatalogLanguage.value;
  const selectedValue = select.value;
  const placeholder = textElement("option", placeholders[language]);
  placeholder.value = "";
  select.replaceChildren(placeholder);
  items.forEach((item) => {
    const option = textElement("option", localizedCatalogLabel(item, language));
    option.value = item.value;
    option.dataset.officialLabel = item.value;
    option.dataset.translationMethod = item.methods?.[language] || item.method || "unknown";
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === selectedValue)) {
    select.value = selectedValue;
  }
}

function applyIntelligenceCatalogLanguage() {
  if (!intelligenceCatalog) return;
  populateCatalogSelect(
    intelligenceCrop,
    intelligenceCatalog.crops,
    { hi: "फसल चुनें", en: "Select a crop" },
  );
  populateCatalogSelect(
    intelligenceDistrict,
    intelligenceCatalog.districts,
    { hi: "सभी जिले", en: "All districts" },
  );
  populateCatalogSelect(
    intelligenceMarket,
    intelligenceCatalog.markets,
    { hi: "सभी मंडियां", en: "All markets" },
  );
  if (lastIntelligenceData) renderIntelligence(lastIntelligenceData);
}

async function loadIntelligenceCatalog() {
  const status = document.querySelector("#intelligence-status");
  intelligenceCrop.disabled = true;
  intelligenceDistrict.disabled = true;
  intelligenceMarket.disabled = true;
  intelligenceCatalogLanguage.disabled = true;
  intelligenceCrop.replaceChildren(textElement("option", "Loading catalog…"));
  try {
    const response = await fetch("/api/v1/catalog?language=all");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Catalog failed to load.");
    intelligenceCatalog = {
      crops: data.mandi_crop_options || [],
      districts: data.district_options || [],
      markets: data.market_options || [],
    };
    applyIntelligenceCatalogLanguage();
    status.textContent = `${formatNumber(intelligenceCatalog.crops.length)} crops, ${formatNumber(intelligenceCatalog.districts.length)} districts and ${formatNumber(intelligenceCatalog.markets.length)} markets loaded from MongoDB.`;
  } catch (error) {
    intelligenceCrop.replaceChildren(textElement("option", "Catalog unavailable"));
    status.textContent = error.message || "Catalog failed to load.";
  } finally {
    intelligenceCrop.disabled = false;
    intelligenceDistrict.disabled = false;
    intelligenceMarket.disabled = false;
    intelligenceCatalogLanguage.disabled = false;
  }
}

async function loadHealth() {
  const state = document.querySelector("#system-state");
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error("Health check failed");
    const data = await response.json();
    document.querySelector("#mandi-count").textContent = formatNumber(data.collections.mandi_prices);
    document.querySelector("#statistics-count").textContent = formatNumber(data.collections.crop_statistics);
    document.querySelector("#documents-count").textContent = formatNumber(data.collections.agriculture_documents);
    state.className = "system-state online";
    state.lastElementChild.textContent = "Data services online";
  } catch (error) {
    state.className = "system-state offline";
    state.lastElementChild.textContent = "Database unavailable";
  }
}

function renderFilters(filters) {
  const block = document.querySelector("#filter-block");
  const list = document.querySelector("#filter-list");
  list.replaceChildren();
  const entries = Object.entries(filters || {});
  block.hidden = entries.length === 0;
  entries.forEach(([key, value]) => list.append(textElement("span", `${humanize(key)}: ${value}`)));
}

function renderSources(sources) {
  const block = document.querySelector("#source-block");
  const list = document.querySelector("#source-list");
  list.replaceChildren();
  block.hidden = !sources.length;
  document.querySelector("#source-count").textContent = `${sources.length} cited`;

  sources.forEach((source) => {
    const card = document.createElement(source.source ? "a" : "div");
    card.className = "source-card";
    if (source.source) {
      const pageSuffix = source.page_number ? `#page=${source.page_number}` : "";
      card.href = `${source.source}${pageSuffix}`;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
    }
    card.append(textElement("strong", source.document_title || source.source_file || "Data source"));
    const detail = source.page_number ? `Page ${source.page_number}` : (source.source_file || "Source record");
    card.append(textElement("small", detail));
    list.append(card);
  });
}

function renderRecords(records) {
  const block = document.querySelector("#records-block");
  const list = document.querySelector("#record-list");
  list.replaceChildren();
  block.hidden = records.length === 0;
  block.open = false;
  document.querySelector("#record-count").textContent = `${records.length} record${records.length === 1 ? "" : "s"}`;

  records.forEach((record) => {
    const card = document.createElement("article");
    card.className = "record-card";
    const values = document.createElement("dl");
    Object.entries(record).forEach(([key, value]) => {
      if (["score", "metadata", "scraped_at"].includes(key) || value == null) return;
      const wrapper = document.createElement("div");
      if (key === "content") wrapper.className = "record-content";
      wrapper.append(textElement("dt", humanize(key)));
      wrapper.append(textElement("dd", typeof value === "object" ? JSON.stringify(value) : value));
      values.append(wrapper);
    });
    card.append(values);
    list.append(card);
  });
}

function showLoading() {
  resultSection.hidden = false;
  loadingState.hidden = false;
  errorState.hidden = true;
  answerState.hidden = true;
  askButton.disabled = true;
  resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showError(message) {
  loadingState.hidden = true;
  answerState.hidden = true;
  errorState.hidden = false;
  document.querySelector("#error-message").textContent = message;
}

function showAnswer(data) {
  loadingState.hidden = true;
  errorState.hidden = true;
  answerState.hidden = false;
  document.querySelector("#answer-text").textContent = data.answer;
  document.querySelector("#intent-badge").textContent = humanize(data.intent);
  const retrieval = data.retrieval || {};
  document.querySelector("#retrieval-badge").textContent = `${humanize(retrieval.mode || "none")} retrieval`;
  document.querySelector("#model-badge").textContent = data.model || "Local model";
  renderFilters(data.filters || {});
  renderSources(data.sources || []);
  renderRecords(data.records || []);
}

const svgNamespace = "http://www.w3.org/2000/svg";

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(svgNamespace, tag);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) element.textContent = value == null ? "—" : String(value);
}

function shortDate(value) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf())
    ? value
    : new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" }).format(date);
}

function renderDailyChart(records) {
  const stage = document.querySelector("#daily-chart");
  stage.replaceChildren();
  if (!records.length) {
    stage.append(textElement("p", "No daily collection records are available."));
    return;
  }
  const width = 760;
  const height = 260;
  const margin = { top: 18, right: 18, bottom: 42, left: 48 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const maximum = Math.max(...records.map((item) => item.records || 0), 1);
  const slot = innerWidth / records.length;
  const barWidth = Math.max(3, Math.min(22, slot * 0.68));
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });

  [0, 0.25, 0.5, 0.75, 1].forEach((fraction) => {
    const y = margin.top + innerHeight * (1 - fraction);
    svg.append(svgElement("line", { x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: "chart-gridline" }));
    const label = svgElement("text", { x: margin.left - 9, y: y + 4, class: "chart-axis-label", "text-anchor": "end" });
    label.textContent = Math.round(maximum * fraction);
    svg.append(label);
  });

  const labelEvery = Math.max(1, Math.ceil(records.length / 6));
  records.forEach((item, index) => {
    const value = item.records || 0;
    const barHeight = value / maximum * innerHeight;
    const x = margin.left + slot * index + (slot - barWidth) / 2;
    const y = margin.top + innerHeight - barHeight;
    const group = svgElement("g");
    const bar = svgElement("rect", { x, y, width: barWidth, height: barHeight, rx: 3, class: "daily-bar" });
    const title = svgElement("title");
    title.textContent = `${item.date}: ${formatNumber(value)} records, ${item.market_count || 0} markets`;
    bar.append(title);
    group.append(bar);
    if (index % labelEvery === 0 || index === records.length - 1) {
      const label = svgElement("text", { x: x + barWidth / 2, y: height - 15, class: "chart-axis-label", "text-anchor": "middle" });
      label.textContent = shortDate(item.date);
      group.append(label);
    }
    svg.append(group);
  });
  stage.append(svg);
  const total = records.reduce((sum, item) => sum + (item.records || 0), 0);
  setText("#daily-chart-total", `${formatNumber(total)} records shown`);
}

function renderRankBars(selector, records) {
  const container = document.querySelector(selector);
  container.replaceChildren();
  const visible = (records || []).slice(0, 7);
  if (!visible.length) {
    container.append(textElement("p", "No distribution data available."));
    return;
  }
  const maximum = Math.max(...visible.map((item) => item.records || 0), 1);
  visible.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "rank-row";
    const label = document.createElement("div");
    label.className = "rank-label";
    label.append(textElement("span", `${index + 1}. ${item.label || "Unknown"}`));
    label.append(textElement("strong", formatNumber(item.records)));
    const track = document.createElement("div");
    track.className = "rank-track";
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(4, item.records / maximum * 100)}%`;
    track.append(fill);
    row.append(label, track);
    container.append(row);
  });
}

function renderMarketMap(geospatial) {
  const container = document.querySelector("#market-map");
  container.replaceChildren();
  const locations = geospatial.locations || [];
  const bounds = geospatial.bounds || {};
  if (!locations.length) {
    setText("#market-map-total", "0 verified points");
    container.append(textElement("p", "No verified market coordinates available."));
    return;
  }
  setText("#market-map-total", `${formatNumber(locations.length)} verified points`);
  const width = 760;
  const height = 330;
  const margin = 35;
  const minLon = bounds.min_longitude;
  const maxLon = bounds.max_longitude;
  const minLat = bounds.min_latitude;
  const maxLat = bounds.max_latitude;
  const project = (longitude, latitude) => ({
    x: margin + (longitude - minLon) / (maxLon - minLon) * (width - margin * 2),
    y: margin + (maxLat - latitude) / (maxLat - minLat) * (height - margin * 2),
  });
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}` });
  svg.append(svgElement("rect", { x: margin, y: margin, width: width - margin * 2, height: height - margin * 2, rx: 18, class: "map-background" }));

  for (let longitude = 84; longitude <= 88; longitude += 1) {
    const point = project(longitude, minLat);
    svg.append(svgElement("line", { x1: point.x, y1: margin, x2: point.x, y2: height - margin, class: "map-gridline" }));
    const label = svgElement("text", { x: point.x, y: height - 12, class: "map-axis-label", "text-anchor": "middle" });
    label.textContent = `${longitude}°E`;
    svg.append(label);
  }
  for (let latitude = 25; latitude <= 27; latitude += 1) {
    const point = project(minLon, latitude);
    svg.append(svgElement("line", { x1: margin, y1: point.y, x2: width - margin, y2: point.y, class: "map-gridline" }));
    const label = svgElement("text", { x: 8, y: point.y + 4, class: "map-axis-label" });
    label.textContent = `${latitude}°N`;
    svg.append(label);
  }

  locations.forEach((location) => {
    const coordinates = location.location && location.location.coordinates;
    if (!coordinates || coordinates.length !== 2) return;
    const point = project(coordinates[0], coordinates[1]);
    const marker = svgElement("circle", { cx: point.x, cy: point.y, r: 5.5, class: "map-marker", tabindex: "0" });
    const title = svgElement("title");
    title.textContent = `${location.market_name}, ${location.district_name} · confidence ${Math.round((location.confidence || 0) * 100)}%`;
    marker.append(title);
    svg.append(marker);
  });
  container.append(svg);
}

function renderCoverage(summary) {
  const percent = summary.geospatial_coverage_percent || 0;
  const ring = document.querySelector("#coverage-ring");
  ring.style.setProperty("--coverage", `${percent * 3.6}deg`);
  setText("#coverage-percent", `${percent}%`);
  setText("#coverage-verified", formatNumber(summary.verified_locations));
  setText("#coverage-unresolved", formatNumber(summary.unresolved_locations));
}

function renderPipeline(pipeline) {
  const latest = pipeline.latest_run;
  const history = pipeline.recent_runs || [];
  const status = latest ? latest.status : "No runs";
  const badge = document.querySelector("#run-status");
  badge.textContent = humanize(status);
  badge.className = `run-pill ${status === "completed" ? "complete" : status === "failed" ? "failed" : ""}`;
  const metrics = (latest && latest.metrics) || {};
  setText("#run-dates", latest ? `${metrics.dates_completed || 0}/${metrics.dates_requested || 0}` : "—");
  setText("#run-records", latest ? formatNumber(metrics.records_processed) : "—");
  setText("#run-writes", latest ? `${formatNumber(metrics.inserted)} / ${formatNumber(metrics.matched)}` : "—");
  setText("#run-success", pipeline.recent_success_percent == null ? "—" : `${pipeline.recent_success_percent}%`);
  const container = document.querySelector("#run-history");
  container.replaceChildren();
  history.slice(0, 8).reverse().forEach((run) => {
    const dot = document.createElement("span");
    dot.className = `history-dot ${run.status || "unknown"}`;
    dot.title = `${run.status || "unknown"} · ${(run.collection_dates || []).join(", ") || "No date"}`;
    container.append(dot);
  });
}

function renderQuality(quality, languages) {
  const meters = document.querySelector("#quality-meters");
  meters.replaceChildren();
  [
    ["Price completeness", quality.price_completeness_percent],
    ["Source provenance", quality.provenance_completeness_percent],
    ["Verified coordinates", quality.coordinate_verification_percent],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "quality-row";
    const heading = document.createElement("div");
    heading.append(textElement("span", label), textElement("strong", `${value || 0}%`));
    const track = document.createElement("div");
    track.className = "quality-track";
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, value || 0))}%`;
    track.append(fill);
    row.append(heading, track);
    meters.append(row);
  });
  const chips = document.querySelector("#language-chips");
  chips.replaceChildren();
  (languages || []).forEach((item) => {
    chips.append(textElement("span", `${String(item.label || "und").toUpperCase()} · ${formatNumber(item.records)}`));
  });
}

function renderDashboard(data) {
  const summary = data.summary || {};
  setText("#kpi-observations", formatNumber(summary.mandi_records));
  setText("#kpi-date-range", summary.earliest_date && summary.latest_date ? `${summary.earliest_date} to ${summary.latest_date}` : "Official daily records");
  setText("#kpi-dates", formatNumber(summary.dates_covered));
  setText("#kpi-latest-date", `Latest date ${summary.latest_date || "—"}`);
  setText("#kpi-markets", formatNumber(summary.markets));
  setText("#kpi-districts", `Across ${formatNumber(summary.districts)} districts · ${formatNumber(summary.crops)} crops`);
  setText("#kpi-locations", formatNumber(summary.verified_locations));
  setText("#kpi-unresolved", `${formatNumber(summary.unresolved_locations)} unresolved, not guessed`);
  setText("#kpi-statistics", formatNumber(summary.crop_statistics));
  setText("#kpi-documents", formatNumber(summary.document_chunks));
  renderCoverage(summary);
  renderDailyChart((data.series || {}).daily_collection || []);
  renderRankBars("#crop-bars", (data.series || {}).top_crops || []);
  renderRankBars("#district-bars", (data.series || {}).top_districts || []);
  renderMarketMap(data.geospatial || {});
  renderPipeline(data.pipeline || {});
  renderQuality(data.quality || {}, (data.series || {}).document_languages || []);
}

async function loadDashboard() {
  const status = document.querySelector("#dashboard-status");
  const days = document.querySelector("#dashboard-window").value;
  status.textContent = "Loading current MongoDB statistics…";
  try {
    const response = await fetch(`/api/v1/dashboard?days=${encodeURIComponent(days)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Dashboard request failed.");
    renderDashboard(data);
    status.textContent = `Updated from live collections · ${data.window_days} most recent data days shown`;
  } catch (error) {
    status.textContent = error.message || "Dashboard data could not be loaded.";
  }
}

const currency = (value) => value == null ? "—" : `₹${formatNumber(Number(value).toFixed(2))}`;

function renderIntelligenceChart(records) {
  const stage = document.querySelector("#intelligence-chart");
  stage.replaceChildren();
  if (!records.length) {
    stage.append(textElement("p", "No matching daily observations are available."));
    return;
  }
  const width = 760;
  const height = 260;
  const margin = { top: 20, right: 20, bottom: 42, left: 62 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const values = records.map((item) => Number(item.average_modal_price));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(maximum - minimum, 1);
  const x = (index) => margin.left + (records.length === 1 ? innerWidth / 2 : index / (records.length - 1) * innerWidth);
  const y = (value) => margin.top + (maximum - value) / range * innerHeight;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });

  [0, 0.5, 1].forEach((fraction) => {
    const value = minimum + range * fraction;
    const lineY = y(value);
    svg.append(svgElement("line", { x1: margin.left, y1: lineY, x2: width - margin.right, y2: lineY, class: "chart-gridline" }));
    const label = svgElement("text", { x: margin.left - 10, y: lineY + 4, class: "chart-axis-label", "text-anchor": "end" });
    label.textContent = `₹${Math.round(value)}`;
    svg.append(label);
  });
  const path = records.map((item, index) => `${index ? "L" : "M"} ${x(index)} ${y(Number(item.average_modal_price))}`).join(" ");
  svg.append(svgElement("path", { d: path, class: "intelligence-line" }));
  const labelEvery = Math.max(1, Math.ceil(records.length / 6));
  records.forEach((item, index) => {
    const point = svgElement("circle", { cx: x(index), cy: y(Number(item.average_modal_price)), r: 4, class: "intelligence-point" });
    const title = svgElement("title");
    title.textContent = `${item.date}: ₹${item.average_modal_price}, ${item.observation_count} observations`;
    point.append(title);
    svg.append(point);
    if (index % labelEvery === 0 || index === records.length - 1) {
      const label = svgElement("text", { x: x(index), y: height - 14, class: "chart-axis-label", "text-anchor": "middle" });
      label.textContent = shortDate(item.date);
      svg.append(label);
    }
  });
  stage.append(svg);
}

function renderMarketComparison(markets) {
  const body = document.querySelector("#intelligence-market-rows");
  body.replaceChildren();
  markets.slice(0, 12).forEach((market) => {
    const row = document.createElement("tr");
    [
      market.latest_price_rank,
      catalogLookup("markets", market.market) || market.market_label || "—",
      catalogLookup("districts", market.district) || market.district_label || "—",
      currency(market.latest_average_price),
      currency(market.window_average_price),
      market.distance_km == null ? "—" : `${market.distance_km} km`,
      formatNumber(market.observation_count),
    ].forEach((value) => row.append(textElement("td", value)));
    body.append(row);
  });
}

function renderIntelligence(data) {
  lastIntelligenceData = data;
  const summary = data.summary || {};
  const freshness = data.freshness || {};
  const locality = data.locality || {};
  document.querySelector("#intelligence-results").hidden = false;
  setText("#intel-latest", currency(summary.latest_average_price));
  setText("#intel-latest-date", freshness.latest_data_date ? `As of ${freshness.latest_data_date}` : "No matching date");
  const change = summary.change_percent == null ? "—" : `${summary.change_percent > 0 ? "+" : ""}${summary.change_percent}%`;
  setText("#intel-change", change);
  setText("#intel-direction", humanize(summary.direction));
  setText("#intel-volatility", summary.daily_volatility_percent == null ? "—" : `${summary.daily_volatility_percent}%`);
  setText("#intel-freshness", humanize(freshness.status));
  const scope = locality.mode === "nearby_verified_markets"
    ? `${locality.verified_markets_in_radius || 0} verified markets within ${locality.radius_km} km`
    : `${formatNumber(summary.markets)} markets · ${formatNumber(summary.dates)} dates`;
  setText("#intel-scope", scope);
  setText("#intel-observations", `${formatNumber(summary.observations)} observations`);
  renderIntelligenceChart(data.daily_series || []);
  renderMarketComparison(data.market_comparison || []);
  const resolutions = Object.entries(data.filter_resolution || {}).filter(
    ([, item]) => item.requested !== item.resolved,
  );
  if (resolutions.length) {
    const status = document.querySelector("#intelligence-status");
    const details = resolutions.map(
      ([field, item]) => `${item.requested} → ${catalogLookup(
        field === "crop" ? "crops" : `${field}s`, item.resolved,
      )}`,
    ).join("; ");
    status.textContent = `Bilingual filter resolved automatically: ${details}. Calculated from stored official observations.`;
  }
  const anomalyList = document.querySelector("#intelligence-anomalies");
  anomalyList.replaceChildren();
  const anomalies = data.anomalies || [];
  if (!anomalies.length) {
    anomalyList.append(textElement("p", "No days crossed the documented two-sigma threshold."));
  } else {
    anomalies.forEach((item) => {
      const card = document.createElement("article");
      card.append(textElement("strong", item.date));
      card.append(textElement("span", `${currency(item.average_modal_price)} · z-score ${item.z_score} · ${item.direction}`));
      anomalyList.append(card);
    });
  }
}

document.querySelector("#intelligence-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.querySelector("#intelligence-status");
  const params = new URLSearchParams({
    crop: document.querySelector("#intelligence-crop").value.trim(),
    days: document.querySelector("#intelligence-days").value,
    display_language: intelligenceCatalogLanguage.value,
  });
  const optional = {
    district: "#intelligence-district",
    market: "#intelligence-market",
    latitude: "#intelligence-latitude",
    longitude: "#intelligence-longitude",
    radius_km: "#intelligence-radius",
  };
  Object.entries(optional).forEach(([key, selector]) => {
    const value = document.querySelector(selector).value.trim();
    if (value && (key !== "radius_km" || params.has("latitude"))) params.set(key, value);
  });
  status.textContent = "Calculating locality and time-aware metrics…";
  document.querySelector("#intelligence-results").hidden = true;
  try {
    const response = await fetch(`/api/v1/mandi-intelligence?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Market analysis failed.");
    renderIntelligence(data);
    const translated = Object.values(data.filter_resolution || {}).some(
      (item) => item.requested !== item.resolved,
    );
    if (!translated) {
      status.textContent = data.summary.observations
        ? "Calculated from stored official observations."
        : "No matching observations were found for this scope.";
    } else if (!data.summary.observations) {
      status.textContent += " No matching observations were found for the resolved scope.";
    }
  } catch (error) {
    status.textContent = error.message || "Market analysis failed.";
  }
});

intelligenceCatalogLanguage.addEventListener("change", applyIntelligenceCatalogLanguage);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;
  showLoading();
  try {
    const response = await fetch("/api/v1/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        answer_language: answerLanguage.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The request failed.");
    showAnswer(data);
  } catch (error) {
    showError(error.message || "The local service could not be reached.");
  } finally {
    askButton.disabled = false;
  }
});

questionInput.addEventListener("input", () => {
  document.querySelector("#character-count").textContent = questionInput.value.length;
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.dataset.question;
    questionInput.dispatchEvent(new Event("input"));
    questionInput.focus();
  });
});

loadHealth();
loadDashboard();
loadIntelligenceCatalog();
document.querySelector("#refresh-dashboard").addEventListener("click", loadDashboard);
document.querySelector("#dashboard-window").addEventListener("change", loadDashboard);

const nearbyForm = document.querySelector("#nearby-form");
const nearbyStatus = document.querySelector("#nearby-status");
const nearbyResults = document.querySelector("#nearby-results");

function renderNearbyPrices(records) {
  nearbyResults.replaceChildren();
  if (!records.length) {
    nearbyStatus.textContent = "No verified nearby market observations matched this search.";
    return;
  }
  nearbyStatus.textContent = `${records.length} recent observation${records.length === 1 ? "" : "s"} found.`;
  records.forEach((record) => {
    const card = document.createElement("article");
    card.className = "nearby-card";
    const heading = textElement("strong", `${record.market || "Market"} · ${record.distance_km} km`);
    const price = record.price == null ? "Price unavailable" : `₹${formatNumber(record.price)} / ${record.unit || "quintal"}`;
    card.append(heading, textElement("span", `${record.crop || "Crop"} · ${price}`));
    card.append(textElement("small", `${record.district || "Bihar"} · ${record.date || "Date unavailable"}`));
    const coordinates = record.market_location && record.market_location.coordinates;
    if (coordinates && coordinates.length === 2) {
      const mapLink = document.createElement("a");
      mapLink.href = `https://www.openstreetmap.org/?mlat=${coordinates[1]}&mlon=${coordinates[0]}#map=13/${coordinates[1]}/${coordinates[0]}`;
      mapLink.target = "_blank";
      mapLink.rel = "noopener noreferrer";
      mapLink.textContent = "View verified point";
      card.append(mapLink);
    }
    nearbyResults.append(card);
  });
}

nearbyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const latitude = document.querySelector("#nearby-latitude").value;
  const longitude = document.querySelector("#nearby-longitude").value;
  const radius = document.querySelector("#nearby-radius").value;
  const crop = document.querySelector("#nearby-crop").value.trim();
  const params = new URLSearchParams({
    latitude,
    longitude,
    radius_km: radius,
    days: "7",
    limit: "30",
  });
  if (crop) params.set("crop", crop);
  nearbyStatus.textContent = "Searching verified market locations…";
  nearbyResults.replaceChildren();
  try {
    const response = await fetch(`/api/v1/mandi-prices/nearby?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Nearby search failed.");
    renderNearbyPrices(data.records || []);
  } catch (error) {
    nearbyStatus.textContent = error.message || "Nearby search failed.";
  }
});

document.querySelector("#use-location").addEventListener("click", () => {
  if (!navigator.geolocation) {
    nearbyStatus.textContent = "This browser does not provide location access.";
    return;
  }
  nearbyStatus.textContent = "Waiting for browser location permission…";
  navigator.geolocation.getCurrentPosition(
    (position) => {
      document.querySelector("#nearby-latitude").value = position.coords.latitude.toFixed(6);
      document.querySelector("#nearby-longitude").value = position.coords.longitude.toFixed(6);
      nearbyStatus.textContent = "Location loaded. Select Find nearby prices.";
    },
    () => {
      nearbyStatus.textContent = "Location was unavailable or permission was declined.";
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
  );
});
