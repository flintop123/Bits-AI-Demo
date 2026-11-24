const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function openMap(satelliteKey = "") {
  const handlers = {};
  const options = {};
  const layers = new Set();
  const views = [];
  const tileRequests = [];
  let zoomEnabled;
  const map = {
    setView: (...args) => { views.push(args); return map; },
    on: () => map,
    removeLayer: (layer) => layers.delete(layer),
    scrollWheelZoom: {
      enabled: () => zoomEnabled,
      enable: () => { zoomEnabled = true; },
      disable: () => { zoomEnabled = false; },
    },
  };
  function newLayer(url, options) {
    const events = {};
    const layer = {
      on(name, cb) { events[name] = cb; return layer; },
      addTo() { layers.add(layer); if (url) tileRequests.push(url); return layer; },
      fire(name) { events[name]?.(); },
      url, options,
    };
    return layer;
  }
  const window = { L: {} };
  const L = {
    map: (_, config) => {
      Object.assign(options, config);
      zoomEnabled = config.scrollWheelZoom;
      return map;
    },
    tileLayer: newLayer,
    layerGroup: () => newLayer(),
    control: { scale: () => newLayer() },
  };
  const source = readFileSync(join(__dirname, "../docs/assets/market-explorer.js"), "utf8");
  const document = { createElement: () => ({ append() {} }) };
  vm.runInNewContext(source, { window, L, document, URL, URLSearchParams });
  const explorer = Object.create(window.MarketExplorer.prototype);
  Object.assign(explorer, {
    basemap: "street",
    satelliteKey,
    refreshBasemapControls() {},
    renderStatus() {},
  });
  explorer.canvas = {
    classList: { add() {} },
    append() {},
    addEventListener(name, listener, config) { handlers[name] = { listener, config }; },
  };
  explorer.initMap();
  return { explorer, layers, map, options, tileRequests, views, wheel: handlers.wheel };
}

test("Leaflet map handles wheel and touch zoom, with a non-passive pinch listener", () => {
  const { options, wheel } = openMap();
  assert.equal(options.scrollWheelZoom, true);
  assert.equal(options.touchZoom, true);
  assert.equal(wheel.config.capture, true);
  assert.equal(wheel.config.passive, false);
});

test("only cancel default browser zoom for a pinch over a zoom-enabled map", () => {
  const { map, wheel } = openMap();
  let cancelled = 0;
  const gesture = { ctrlKey: true, cancelable: true, preventDefault: () => cancelled++ };
  wheel.listener(gesture);
  wheel.listener({ ...gesture, ctrlKey: false });
  wheel.listener({ ...gesture, cancelable: false });
  map.scrollWheelZoom.disable();
  wheel.listener(gesture);
  assert.equal(cancelled, 1);
});

test("satellite is opt-in and switching basemaps leaves map position and overlays intact", () => {
  assert.equal(openMap().explorer.basemaps.satellite, undefined);
  const { explorer, layers, tileRequests, views } = openMap("browser-fixture");
  const { street, satellite } = explorer.basemaps;
  assert.equal(tileRequests.length, 1);
  assert.equal(layers.has(satellite), false);
  const pins = explorer.pins, radius = explorer.circleLayer;

  explorer.setBasemap("satellite");
  assert.equal(layers.has(street), false);
  assert.equal(layers.has(satellite), true);
  assert.equal(layers.has(pins), true);
  assert.equal(layers.has(radius), true);
  assert.equal(views.length, 1, "switching must not pan or change zoom");
  assert.match(satellite.options.attribution, /MapTiler/);
  assert.match(tileRequests[1], /api\.maptiler\.com\/tiles\/satellite-v2\/.*\?key=browser-fixture$/);
});

test("complete satellite tile failure falls back to Street", () => {
  const { explorer, layers } = openMap("browser-fixture");
  const { street, satellite } = explorer.basemaps;
  explorer.setBasemap("satellite");
  satellite.fire("loading");
  satellite.fire("tileerror");
  satellite.fire("load");
  assert.equal(explorer.basemap, "street");
  assert.equal(explorer.satelliteFailed, true);
  assert.equal(layers.has(street), true);
  assert.equal(layers.has(satellite), false);
});
