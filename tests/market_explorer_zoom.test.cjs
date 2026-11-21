const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function openMap() {
  const handlers = {};
  const options = {};
  let zoomEnabled;
  const map = {
    setView: () => map,
    on: () => map,
    scrollWheelZoom: {
      enabled: () => zoomEnabled,
      enable: () => { zoomEnabled = true; },
      disable: () => { zoomEnabled = false; },
    },
  };
  const layer = { on: () => layer, addTo: () => layer };
  const window = { L: {} };
  const L = {
    map: (_, config) => {
      Object.assign(options, config);
      zoomEnabled = config.scrollWheelZoom;
      return map;
    },
    tileLayer: () => layer,
    layerGroup: () => layer,
    control: { scale: () => layer },
  };
  const source = readFileSync(join(__dirname, "../docs/assets/market-explorer.js"), "utf8");
  vm.runInNewContext(source, { window, L });
  const explorer = Object.create(window.MarketExplorer.prototype);
  explorer.canvas = {
    classList: { add() {} },
    addEventListener(name, listener, config) { handlers[name] = { listener, config }; },
  };
  explorer.initMap();
  return { map, options, wheel: handlers.wheel };
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
