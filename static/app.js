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
