"use strict";

(() => {
  const text = (el, value) => { el.textContent = value; return el; };
  const make = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value != null) text(element, value);
    if (className) element.className = className;
    return element;
  };
  const point = (lat, lon) => Number.isFinite(lat) && Number.isFinite(lon) &&
    Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
  const radians = (x) => x * Math.PI / 180;

  function distanceKm(a, b) {
    const sinLat = Math.sin(radians(b[0] - a[0]) / 2);
    const sinLon = Math.sin(radians(b[1] - a[1]) / 2);
    const h = sinLat ** 2 + Math.cos(radians(a[0])) * Math.cos(radians(b[0])) * sinLon ** 2;
    return 2 * 6371.0088 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
  }

  function sourceLink(raw) {
    try {
      const url = new URL(raw);
      return url.protocol === "https:" && !url.username && !url.password ? url.href : "";
    } catch (_) { return ""; }
  }

  class MarketExplorer {
    constructor(root, { translate = (en) => en, onLiveSearch = null } = {}) {
      this.root = root;
      this.tr = translate;
      this.onLiveSearch = onLiveSearch;
      this.canvas = root.querySelector("#market-map");
      this.controls = root.querySelector(".market-explorer-controls");
      this.directory = root.querySelector(".market-explorer-directory");
      this.details = root.querySelector(".market-explorer-details");
      this.summary = root.querySelector(".market-explorer-summary");
      this.status = root.querySelector(".market-explorer-status");
      this.markets = [];
      this.radius = 75;
      this.tileStatus = "loading";
      this.buildControls();
      this.initMap();
    }

    buildControls() {
      this.search = make("input");
      this.search.type = "search";
      this.search.maxLength = 100;
      this.district = make("select");
      this.radiusInput = make("input");
      Object.assign(this.radiusInput, { type: "number", min: "1", max: "300", step: "1", value: "75" });
      this.searchLabel = this.field(this.search);
      this.districtLabel = this.field(this.district);
      this.radiusLabel = this.field(this.radiusInput);
      this.pickButton = this.button(this.controls, () => {
        if (!this.map) return;
        this.choosing = !this.choosing;
        this.canvas.classList.toggle("map-choosing", this.choosing);
        this.refreshLabels();
      });
      this.fitButton = this.button(this.controls, () => this.fit());
      this.clearButton = this.button(this.controls, () => {
        this.search.value = this.district.value = "";
        this.origin = this.active = this.liveResult = null;
        this.choosing = false;
        this.canvas.classList.remove("map-choosing");
        this.update(true);
      });
      this.search.addEventListener("input", () => this.update());
      this.district.addEventListener("change", () => this.update(true));
      const updateRadius = (settled) => {
        if (this.radiusInput.checkValidity() && this.radiusInput.value) {
          const next = Number(this.radiusInput.value);
          if (next !== this.radius) {
            this.radius = next;
            this.liveResult = null;
          }
          if (!settled && !this.origin) return;
          this.update(settled);
        } else if (settled) {
          this.radiusInput.value = this.radius;
        }
      };
      this.radiusInput.addEventListener("input", () => updateRadius(false));
      this.radiusInput.addEventListener("change", () => updateRadius(true));
    }

    field(input) {
      const label = make("label", null, "market-explorer-field");
      const caption = make("span");
      label.append(caption, input);
      this.controls.append(label);
      return caption;
    }

    button(parent, action) {
      const button = make("button");
      button.type = "button";
      button.addEventListener("click", action);
      parent.append(button);
      return button;
    }

    initMap() {
      if (!window.L) {
        this.tileStatus = "offline";
        return;
      }
      this.canvas.classList.add("has-live-map");
      this.map = L.map(this.canvas, { scrollWheelZoom: false, minZoom: 5, maxZoom: 17 })
        .setView([25.8, 85.6], 7);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).on("tileload", () => {
        if (this.tileStatus === "loading") this.tileStatus = "loaded";
        else if (this.tileStatus === "offline") this.tileStatus = "partial";
        this.renderStatus();
      }).on("tileerror", () => {
        this.tileStatus = ["loaded", "partial"].includes(this.tileStatus) ? "partial" : "offline";
        this.renderStatus();
      }).addTo(this.map);
      L.control.scale({ imperial: false, position: "bottomleft" }).addTo(this.map);
      this.pins = L.layerGroup().addTo(this.map);
      this.circleLayer = L.layerGroup().addTo(this.map);
      this.map.on("click", ({ latlng }) => {
        if (!this.choosing) return;
        this.choosing = false;
        this.canvas.classList.remove("map-choosing");
        this.setOrigin([latlng.lat, latlng.lng], this.tr("Selected point", "चुना गया स्थान"));
      });
      if (window.ResizeObserver) new ResizeObserver(() => this.map.invalidateSize({ pan: false })).observe(this.canvas);
    }

    setMarkets(raw, { fit = !this.markets.length } = {}) {
      const seen = new Set();
      this.markets = [];
      for (const item of raw || []) {
        const coordinates = item.location?.coordinates;
        const p = point(item.latitude ?? coordinates?.[1], item.longitude ?? coordinates?.[0]);
        if (!p) continue;
        const market = String(item.market_name ?? item.market ?? this.tr("Market", "मंडी"));
        const district = String(item.district_name ?? item.district ?? this.tr("Bihar", "बिहार"));
        const key = String(item.market_code ?? `${market}:${district}:${p.join(",")}`);
        if (seen.has(key)) continue;
        seen.add(key);
        this.markets.push({ key, market, district, p, source: sourceLink(item.coordinate_source_url ?? item.osm_url ?? item.source),
          confidence: item.confidence, precision: item.location_precision ?? item.precision, code: item.market_code });
      }
      this.markets.sort((a, b) => a.district.localeCompare(b.district) || a.market.localeCompare(b.market));
      const previous = this.district.value;
      this.district.replaceChildren(new Option("", ""), ...[...new Set(this.markets.map((item) => item.district))]
        .map((district) => new Option(district, district)));
      if ([...this.district.options].some((option) => option.value === previous)) this.district.value = previous;
      this.active = this.markets.find((item) => item.key === this.active?.key) || null;
      this.update(fit);
    }

    refreshLabels() {
      const t = this.tr;
      this.searchLabel.textContent = t("Find a market", "मंडी खोजें");
      this.search.placeholder = t("Market, district or code", "मंडी, जिला या कोड");
      this.districtLabel.textContent = t("District", "जिला");
      if (this.district.options.length) this.district.options[0].text = t("All districts", "सभी जिले");
      this.radiusLabel.textContent = t("Radius (km)", "त्रिज्या (किमी)");
      this.pickButton.hidden = !this.map;
      this.pickButton.textContent = this.choosing ? t("Click a point on the map", "मानचित्र पर स्थान चुनें") : t("Choose centre on map", "मानचित्र पर केंद्र चुनें");
      this.pickButton.setAttribute("aria-pressed", String(Boolean(this.choosing)));
      this.fitButton.hidden = !this.map;
      this.fitButton.textContent = t("Fit map", "मानचित्र समायोजित करें");
      this.clearButton.textContent = t("Reset map", "मानचित्र रीसेट करें");
    }

    renderStatus() {
      const t = this.tr;
      this.status.textContent = {
        loading: t("Loading map tiles…", "मानचित्र लोड हो रहा है…"),
        loaded: t("OpenStreetMap tiles loaded.", "OpenStreetMap मानचित्र उपलब्ध है।"),
        partial: t("Some tiles are unavailable. Verified points and the directory still work.", "कुछ टाइल उपलब्ध नहीं हैं। सत्यापित बिंदु और सूची उपलब्ध हैं।"),
        offline: t("Basemap unavailable. You can still explore verified markets and measure a radius.", "आधार मानचित्र उपलब्ध नहीं है। आप मंडियों और दूरी को देख सकते हैं।"),
      }[this.tileStatus];
    }

    setOrigin(p, label) {
      this.origin = { p, label };
      this.liveResult = null;
      this.update(true);
    }

    setLiveResults(data) {
      const coordinates = data.origin?.coordinates;
      const p = point(coordinates?.[1], coordinates?.[0]);
      if (!p || !Number.isFinite(data.radius_km)) return;
      this.radius = data.radius_km;
      this.radiusInput.value = this.radius;
      this.origin = { p, label: this.tr("Live search centre", "लाइव खोज केंद्र") };
      const keys = new Set();
      const rows = Array.isArray(data.records) ? data.records : [];
      for (const row of rows) {
        if (row.market_code != null) keys.add(String(row.market_code));
      }
      this.liveResult = { keys, capped: rows.length >= 100 };
      this.update(true);
    }

    clearLiveResults() {
      this.liveResult = null;
      this.update();
    }

    select(key, fromList) {
      this.active = this.markets.find((item) => item.key === key);
      if (!this.active) return;
      this.renderDetails();
      for (const button of this.directory.querySelectorAll("button[data-key]")) {
        button.setAttribute("aria-current", String(button.dataset.key === key));
      }
      for (const [marketKey, marker] of this.markers || []) {
        marker.getElement()?.classList.toggle("market-pin-active", marketKey === key);
      }
      if (fromList && this.map) {
        this.map.panTo(this.active.p);
        this.markers.get(key)?.openPopup();
      }
    }

    renderDetails() {
      const t = this.tr;
      this.details.replaceChildren();
      if (this.active) {
        const { market, district, p, source, confidence, code } = this.active;
        this.details.append(
          make("strong", market),
          make("span", `${district}${code != null ? ` · #${code}` : ""} · ${p[0].toFixed(4)}, ${p[1].toFixed(4)}`),
        );
        const provenance = t("Verified locality centroid, not a surveyed entrance.", "सत्यापित स्थानीयता केंद्र, सर्वेक्षित प्रवेश द्वार नहीं।");
        const score = Number.isFinite(confidence) ? ` · ${t("Confidence", "विश्वास")}: ${Math.round(confidence * 100)}%` : "";
        this.details.append(make("small", provenance + score));
        if (source) {
          const link = make("a", t("Coordinate source", "निर्देशांक स्रोत"));
          Object.assign(link, { href: source, target: "_blank", rel: "noopener noreferrer" });
          this.details.append(link);
        }
        const selected = this.active;
        this.button(this.details, () => this.setOrigin(selected.p, selected.market)).textContent =
          t("Use market as centre", "मंडी को केंद्र बनाएं");
      } else {
        this.details.append(make("small", t("Select a market to see its coordinates and evidence.", "निर्देशांक और साक्ष्य देखने के लिए मंडी चुनें।")));
      }
      if (this.origin) {
        this.details.append(make("span", `${this.origin.label} · ${this.radius} km`, "market-explorer-origin"));
        if (this.onLiveSearch) {
          this.button(this.details, () => this.onLiveSearch(this.origin.p, this.radius)).textContent =
            t("Find live price records", "लाइव मूल्य रिकॉर्ड खोजें");
        }
      }
    }

    update(fit = false) {
      const t = this.tr;
      this.refreshLabels();
      this.renderStatus();
      const query = this.search.value.normalize("NFC").toLocaleLowerCase().trim();
      const origin = this.origin?.p;
      this.visible = this.markets.filter((item) =>
        (!this.district.value || item.district === this.district.value) &&
        (!query || `${item.market} ${item.district} ${item.code ?? ""}`.normalize("NFC").toLocaleLowerCase().includes(query)));
      this.ordered = this.visible.map((item) => ({
        ...item, distance: origin ? distanceKm(origin, item.p) : null,
      }));
      if (origin) this.ordered.sort((a, b) => a.distance - b.distance);
      if (this.active && !this.visible.some((item) => item.key === this.active.key)) this.active = null;
      this.directory.replaceChildren();
      const inside = this.ordered.filter((item) => item.distance !== null && item.distance <= this.radius).length;
      const radiusLabel = origin ? ` · ${inside} ${t("within the straight-line radius", "सीधी दूरी की त्रिज्या में")}` : "";
      const liveLabel = this.liveResult
        ? ` · ${this.liveResult.keys.size} ${t("markets in returned price records", "प्राप्त मूल्य रिकॉर्ड में मंडियाँ")}${this.liveResult.capped ? t(" (record limit reached)", " (रिकॉर्ड सीमा पूरी)") : ""}` : "";
      this.summary.textContent = `${this.visible.length}/${this.markets.length} ${t("verified markets shown", "सत्यापित मंडियाँ दिखाई गईं")}${radiusLabel}${liveLabel}`;
      if (!this.ordered.length) this.directory.append(make("p", t("No markets match the filters.", "फ़िल्टर से कोई मंडी नहीं मिली।")));
      for (const market of this.ordered) {
        const item = this.button(this.directory, () => this.select(market.key, true));
        item.dataset.key = market.key;
        item.setAttribute("aria-current", String(market.key === this.active?.key));
        item.append(make("strong", market.market), make("small", market.district +
          (market.distance === null ? "" : ` · ${market.distance.toFixed(1)} km`)));
      }
      this.renderDetails();
      this.renderPins();
      if (fit) this.fit();
    }

    renderPins() {
      if (!this.map) {
        this.canvas.textContent = this.tr("Use the market directory below when tiles are unavailable.", "टाइल उपलब्ध न होने पर नीचे की मंडी सूची का उपयोग करें।");
        return;
      }
      this.pins.clearLayers();
      this.circleLayer.clearLayers();
      this.markers = new Map();
      for (const market of this.ordered) {
        const isMatch = this.liveResult ? this.liveResult.keys.has(market.key) : market.distance !== null && market.distance <= this.radius;
        const icon = L.divIcon({
          className: `market-pin ${isMatch ? "market-pin-nearby" : ""}${market.key === this.active?.key ? " market-pin-active" : ""}`,
          iconSize: [18, 18], iconAnchor: [9, 9],
        });
        const popup = make("span", `${market.market} · ${market.district}${market.distance === null ? "" : ` · ${market.distance.toFixed(1)} km`}`);
        const marker = L.marker(market.p, { icon, title: `${market.market} · ${market.district}`, keyboard: true, riseOnHover: true })
          .bindPopup(popup).addTo(this.pins);
        marker.getElement()?.setAttribute("aria-label", `${market.market}, ${market.district}`);
        marker.on("click", () => this.select(market.key, false));
        this.markers.set(market.key, marker);
      }
      if (this.origin) {
        this.circle = L.circle(this.origin.p, { radius: this.radius * 1000, color: "#a94b1b", weight: 2, fillOpacity: .10, interactive: false }).addTo(this.circleLayer);
        L.circleMarker(this.origin.p, { radius: 5, color: "#773714", fillOpacity: 1, interactive: false }).addTo(this.circleLayer);
      } else {
        this.circle = null;
      }
    }

    fit() {
      if (!this.map) return;
      if (this.circle) this.map.fitBounds(this.circle.getBounds(), { padding: [28, 28], maxZoom: 14 });
      else if (this.visible.length) this.map.fitBounds(this.visible.map((item) => item.p), { padding: [30, 30], maxZoom: 12 });
      else this.map.setView([25.8, 85.6], 7);
    }
  }

  window.MarketExplorer = MarketExplorer;
})();
