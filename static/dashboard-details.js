/* Read-only dashboard drill-downs. The first view loads no detail queries. */
const KPI_DETAILS = {
  observations: {
    title: "Mandi observations",
    intro: "A quick check of the stored official mandi rows and how complete they are.",
  },
  dates: {
    title: "Dates covered",
    intro: "Mandi rows and distinct market codes by date in the selected window. The headline counts all stored dates.",
    section: "dates",
  },
  markets: {
    title: "Observed markets",
    intro: "Official price rows grouped by market code. A market can have prices even if its location is not verified.",
    section: "markets",
  },
  locations: {
    title: "Verified locations",
    intro: "Verified coordinates are locality centroids, not market gates. Unresolved means there is no matching verified coordinate for that market code.",
    section: "markets",
  },
  crop_statistics: {
    title: "Crop statistics",
    intro: "Historical crop record counts and periods. Area, production and yield are distinct measures with different units.",
    section: "crop_statistics",
  },
  documents: {
    title: "Report passages",
    intro: "Passages are page-linked pieces of indexed reports, not a count of unique reports or uploaded PDFs.",
    section: "documents",
  },
};

class DashboardDetails {
  constructor(root, {ask} = {}) {
    this.root = root;
    this.ask = ask;
    this.panel = root.querySelector("#kpi-details");
    this.title = root.querySelector("#kpi-detail-title");
    this.intro = root.querySelector("#kpi-detail-intro");
    this.status = root.querySelector("#kpi-detail-status");
    this.content = root.querySelector("#kpi-detail-content");
    this.insight = root.querySelector("#daily-insight");
    this.buttons = [...root.querySelectorAll("[data-kpi]")];
    this.buttons.forEach((button) => button.addEventListener("click", () => {
      const key = button.dataset.kpi;
      if (this.active === key) this.close();
      else this.open(key, button);
    }));
    root.querySelector("#kpi-detail-close").addEventListener("click", () => this.close());
    root.querySelector("#open-date-details").addEventListener("click", (event) => {
      this.open("dates", event.currentTarget);
    });
    this.cache = new Map();
    this.active = null;
    this.snapshot = null;
    this.date = null;
    this.opener = null;
    this.pending = null;
  }

  update(snapshot) {
    this.snapshot = snapshot;
    this.cache.clear();
    if (this.active) this.load();
  }

  close() {
    if (this.pending) this.pending.abort();
    this.pending = null;
    this.active = null;
    this.date = null;
    this.panel.hidden = true;
    this.buttons.forEach((button) => button.setAttribute("aria-expanded", "false"));
    this.updateDateSelection();
    const focusTarget = this.opener?.isConnected ? this.opener : this.root.querySelector("#open-date-details");
    focusTarget?.focus({preventScroll: true});
    this.opener = null;
  }

  open(key, opener, date = null) {
    if (!KPI_DETAILS[key]) return;
    this.active = key;
    this.date = date;
    this.opener = opener;
    this.panel.hidden = false;
    this.buttons.forEach((button) => button.setAttribute("aria-expanded", String(button.dataset.kpi === key)));
    this.title.textContent = KPI_DETAILS[key].title;
    this.intro.textContent = KPI_DETAILS[key].intro;
    this.updateDateSelection();
    this.load();
    this.title.focus({preventScroll: true});
    this.panel.scrollIntoView({block: "nearest"});
  }

  dateLabel(row) {
    if (!row) return "Hover, tap or focus a bar to explore a collection date.";
    const observed = [`${this.number(row.records)} mandi rows`];
    if (row.market_count != null) observed.push(`${this.number(row.market_count)} markets`);
    if (row.district_count != null) observed.push(`${this.number(row.district_count)} districts`);
    return `${row.date} · ${observed.join(" · ")}`;
  }

  previewDate(row) {
    const current = row || this.dailySeries().find((item) => item.date === this.date);
    this.insight.textContent = !current && this.snapshot && !this.dailySeries().length
      ? "There are no collection dates to explore." : this.dateLabel(current);
  }

  updateDateSelection() {
    this.root.querySelectorAll("[data-chart-date]").forEach((bar) => {
      bar.setAttribute("aria-pressed", String(bar.dataset.chartDate === this.date));
    });
    this.previewDate(null);
  }

  dailySeries() {
    return this.snapshot?.series?.daily_collection || [];
  }

  number(value) {
    return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("en-IN").format(value) : "—";
  }

  node(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  link(text, href) {
    const link = this.node("a", text);
    link.href = href;
    return link;
  }

  actions(items, askMode) {
    const actions = this.node("div", null, "kpi-detail-actions");
    items.forEach(([label, href]) => actions.append(this.link(label, href)));
    if (askMode && this.ask) {
      const button = this.node("button", "Ask AgriAgent", "secondary-button");
      button.type = "button";
      button.setAttribute("aria-haspopup", "dialog");
      button.addEventListener("click", () => this.ask(button, askMode));
      actions.append(button);
    }
    return actions;
  }

  table(label, columns, rows, renderRow) {
    const container = this.node("div", null, "kpi-table-wrap");
    container.tabIndex = 0;
    container.setAttribute("role", "region");
    container.setAttribute("aria-label", label);
    const table = this.node("table", null, "kpi-table");
    const head = this.node("thead");
    const headings = this.node("tr");
    columns.forEach((label) => {
      const column = this.node("th", label);
      column.scope = "col";
      headings.append(column);
    });
    head.append(headings);
    const body = this.node("tbody");
    rows.forEach((item) => {
      const row = this.node("tr");
      if (item.date && item.date === this.date) row.setAttribute("aria-current", "date");
      renderRow(item).forEach((value) => {
        const cell = this.node("td");
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value == null || value === "" ? "—" : value;
        row.append(cell);
      });
      body.append(row);
    });
    table.append(head, body);
    container.append(table);
    return container;
  }

  empty(message = "There are no rows for this view.") {
    return this.node("p", message, "kpi-empty");
  }

  observations() {
    const summary = this.snapshot?.summary || {};
    const quality = this.snapshot?.quality || {};
    if (summary.mandi_records == null) {
      this.content.append(this.empty("The collection summary is not available yet."));
      return;
    }
    if (!summary.mandi_records) {
      this.content.append(this.empty("There are no stored official mandi rows to summarize."));
      return;
    }
    const facts = [
      ["Stored official rows", this.number(summary.mandi_records)],
      ["Rows with a numeric price", this.number(quality.price_complete_records)],
      ["Rows with recorded provenance", this.number(quality.provenance_complete_records)],
    ];
    const grid = this.node("dl", null, "kpi-facts");
    facts.forEach(([label, value]) => {
      const item = this.node("div");
      item.append(this.node("dt", label), this.node("dd", value));
      grid.append(item);
    });
    this.content.append(grid, this.actions([
      ["Explore price movement", "#intelligence-heading"], ["Search by location", "#nearby-heading"],
    ], "direct"));
  }

  dates(rows) {
    if (!rows.length) return void this.content.append(this.empty("No observed dates in this window."));
    this.content.append(this.table("Mandi data by collection date", ["Date", "Mandi rows", "Market codes"],
      [...rows].sort((left, right) => String(right.date).localeCompare(String(left.date))),
      (row) => [row.date, this.number(row.records), this.number(row.market_count)]));
  }

  markets(rows, truncated) {
    const filters = this.node("div", null, "kpi-market-filters");
    const searchLabel = this.node("label", "Find a market");
    const search = this.node("input");
    search.type = "search";
    search.placeholder = "Name, district or code";
    searchLabel.append(search);
    const statusLabel = this.node("label", "Coordinates");
    const select = this.node("select");
    [["all", "All markets"], ["verified", "Verified only"], ["unresolved", "Unresolved only"]].forEach(([value, label]) => {
      const option = this.node("option", label);
      option.value = value;
      select.append(option);
    });
    select.value = this.active === "locations" ? "verified" : "all";
    statusLabel.append(select);
    filters.append(searchLabel, statusLabel);
    const result = this.node("div");
    const update = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const visible = rows.filter((row) => (select.value === "all" || row.verification_status === select.value)
        && [row.market, row.market_code, row.district].some((value) => String(value ?? "").toLocaleLowerCase().includes(query)));
      this.status.textContent = `${this.number(visible.length)} of ${this.number(rows.length)} loaded markets${truncated ? " · first 200 by observation count" : ""}.`;
      const listing = visible.length ? this.table("Observed market codes and coordinate status",
        ["Market", "Coordinates", "Code", "Mandi rows", "District"], visible,
        (row) => [row.market,
          this.node("span",
            {verified: "Verified", unresolved: "Unresolved"}[row.verification_status] || "Not reported",
            row.verification_status === "verified" ? "kpi-status-verified" : "kpi-status-neutral"),
          row.market_code, this.number(row.records), row.district])
        : this.empty(rows.length ? "No market matches these filters." : "No official observed market codes were found.");
      if (visible.length) listing.classList.add("kpi-market-table");
      result.replaceChildren(listing);
    };
    search.addEventListener("input", update);
    select.addEventListener("change", update);
    this.content.append(filters, result, this.actions([["View verified market map", "#market-explorer"]]));
    update();
  }

  crops(rows) {
    const data = rows.length ? this.table("Historical crop-statistics records",
      ["Crop", "Records", "First period", "Latest period"], rows,
      (row) => [row.crop, this.number(row.records), row.earliest_year, row.latest_year])
      : this.empty("No historical crop-statistics rows were found.");
    this.content.append(data, this.actions([], "direct"));
  }

  documents(rows) {
    const data = rows.length ? this.table("Indexed report passages",
      ["Report", "Language", "Passages"], rows,
      (row) => [row.document_title || "Title not recorded",
        {en: "English", hi: "Hindi", mixed: "Mixed"}[row.language] || row.language || "Not recorded", this.number(row.records)])
      : this.empty("No report passages are indexed.");
    this.content.append(data, this.actions([["Upload your own PDF", "#viva-upload-heading"]], "document_chat"));
  }

  render(result) {
    const rows = Array.isArray(result.rows) ? result.rows : [];
    this.status.textContent = `${this.number(rows.length)} ${rows.length === 1 ? "row" : "rows"} shown${result.truncated ? " · first 200 by record count" : ""}.`;
    if (this.active === "dates") this.dates(rows);
    else if (this.active === "markets" || this.active === "locations") this.markets(rows, result.truncated);
    else if (this.active === "crop_statistics") this.crops(rows);
    else if (this.active === "documents") this.documents(rows);
  }

  async load() {
    if (this.pending) this.pending.abort();
    this.content.replaceChildren();
    this.status.textContent = "";
    const key = this.active;
    const section = KPI_DETAILS[key]?.section;
    if (key === "observations") return this.observations();
    if (!section) return;

    const days = this.snapshot?.window_days ?? this.root.querySelector("#dashboard-window").value;
    const params = new URLSearchParams({section, days});
    if (this.cache.has(params.toString())) return this.render(this.cache.get(params.toString()));
    this.status.textContent = "Loading stored records…";
    const pending = new AbortController();
    this.pending = pending;
    try {
      const response = await fetch(`/api/v1/dashboard/details?${params}`, {signal: pending.signal});
      if (!response.ok) throw new Error("Detail lookup unavailable");
      const data = await response.json();
      if (pending.signal.aborted || this.active !== key) return;
      if (data.section !== section || !Array.isArray(data.rows)) throw new Error("Unexpected detail response");
      this.cache.set(params.toString(), data);
      this.render(data);
    } catch (error) {
      if (pending.signal.aborted || this.active !== key) return;
      if (key === "dates" && this.dailySeries().length) {
        this.status.textContent = "Showing the dates already loaded in the chart.";
        this.dates(this.dailySeries());
      } else {
        this.status.textContent = "This breakdown is not available. Keep exploring the dashboard or try again.";
        if (section === "markets") this.content.append(this.actions([["View verified market map", "#market-explorer"]]));
      }
    } finally {
      if (this.pending === pending) this.pending = null;
    }
  }
}
