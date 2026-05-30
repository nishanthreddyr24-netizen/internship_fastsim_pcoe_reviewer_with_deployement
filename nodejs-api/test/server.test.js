"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  createServer,
  fetchSupabaseChargers,
  mapLegacyRequest,
  mapLegacyResponse,
} = require("../src/server");

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function legacyPayload(overrides = {}) {
  return {
    vehicle_id: "IN-2025-0007",
    start_lat: 28.597861,
    start_lon: 77.032485,
    end_lat: 28.556,
    end_lon: 77.1,
    environment: {
      ambient_temp_c: 25,
      wind_speed_kph: 0,
      wind_direction_deg: 0,
      precipitation_mm: 0,
    },
    vehicle_state: {
      starting_soc: 0.8,
      protection_soc: 0.15,
      state_of_health: 0.95,
      hvac_power_kw: 0,
    },
    ...overrides,
  };
}

async function withServer(server, callback) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    await callback(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("maps the legacy PDF payload to the FastAPI routing contract", () => {
  const mapped = mapLegacyRequest(legacyPayload(), {
    SUPABASE_SEARCH_RADIUS_METERS: "25000",
  });

  assert.equal(mapped.vehicle_id, "IN-2025-0007");
  assert.deepEqual(mapped.start, { lat: 28.597861, lon: 77.032485 });
  assert.deepEqual(mapped.end, { lat: 28.556, lon: 77.1 });
  assert.equal(mapped.vehicle_state.state_of_health, 0.95);
  assert.equal(mapped.charger_radius_km, 25);
  assert.equal(mapped.include_charger_routes, true);
});

test("uses Supabase rows in the legacy response when available", () => {
  const response = mapLegacyResponse(
    {
      primary_route_edges: [{ edge_index: 0 }],
      simulation: { status: "depletion_triggered" },
      recommended_chargers: [{ station_id: "local" }],
    },
    { rows: [{ station_id: "supabase" }], source: "supabase" },
  );

  assert.equal(response.status, "success");
  assert.equal(response.charger_source, "supabase");
  assert.deepEqual(response.chargers, [{ station_id: "supabase" }]);
});

test("falls back to local chargers when Supabase returns no rows", () => {
  const response = mapLegacyResponse(
    {
      primary_route_edges: [{ edge_index: 0 }],
      simulation: { status: "depletion_triggered" },
      recommended_chargers: [{ station_id: "local" }],
    },
    { rows: [], source: "local_fallback_supabase_empty" },
  );

  assert.equal(response.charger_source, "local_fallback_supabase_empty");
  assert.deepEqual(response.chargers, [{ station_id: "local" }]);
});

test("calls the configured Supabase RPC with depletion coordinates", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return jsonResponse([{ station_id: "rpc-station" }]);
  };

  const result = await fetchSupabaseChargers(
    { lat: 28.57, lon: 77.05 },
    {
      SUPABASE_URL: "https://example.supabase.co",
      SUPABASE_KEY: "secret",
      SUPABASE_SEARCH_RADIUS_METERS: "25000",
    },
    fetchImpl,
  );

  assert.equal(result.source, "supabase");
  assert.equal(calls[0].url, "https://example.supabase.co/rest/v1/rpc/find_nearest_chargers");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    deplete_lat: 28.57,
    deplete_lng: 77.05,
    search_radius_meters: 25000,
  });
});

test("passes /api/v1 requests through to Python", async () => {
  const calls = [];
  const server = createServer({
    env: { PYTHON_ENGINE_URL: "http://python:8000" },
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return jsonResponse({ status: "ok" });
    },
  });

  await withServer(server, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/api/v1/physics/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ route_edges: [] }),
    });

    assert.equal(response.status, 200);
    assert.equal(calls[0].url, "http://python:8000/api/v1/physics/simulate");
    assert.equal(calls[0].options.method, "POST");
  });
});

test("health stays ok when optional Valhalla is unreachable", async () => {
  const server = createServer({
    env: {
      PYTHON_ENGINE_URL: "http://python:8000",
      VALHALLA_URL: "http://valhalla:8002",
      VALHALLA_HEALTH_TIMEOUT_MS: "5",
    },
    fetchImpl: async (url) => {
      if (url === "http://python:8000/health") {
        return jsonResponse({ status: "ok" });
      }
      if (url === "http://python:8000/diagnostics/runtime") {
        return jsonResponse({ status: "ok", simulation_engine: "fastsim" });
      }
      throw new Error("fetch failed");
    },
  });

  await withServer(server, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/health`);
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.status, "ok");
    assert.equal(body.checks.python, "ok");
    assert.equal(body.checks.valhalla, "unreachable");
  });
});

test("legacy route combines Python routing with Supabase charger lookup", async () => {
  const calls = [];
  const server = createServer({
    env: {
      PYTHON_ENGINE_URL: "http://python:8000",
      SUPABASE_URL: "https://example.supabase.co",
      SUPABASE_KEY: "secret",
    },
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      if (url === "http://python:8000/api/v1/routing/recommend") {
        return jsonResponse({
          primary_route_edges: [{ edge_index: 0 }],
          simulation: {
            status: "depletion_triggered",
            depletion_coordinate: { lat: 28.57, lon: 77.05 },
          },
          recommended_chargers: [{ station_id: "local" }],
        });
      }
      return jsonResponse([{ station_id: "supabase" }]);
    },
  });

  await withServer(server, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/api/calculate-ev-route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(legacyPayload()),
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.charger_source, "supabase");
    assert.equal(body.route_edges.length, 1);
    assert.equal(body.chargers[0].station_id, "supabase");
    assert.equal(calls[0].url, "http://python:8000/api/v1/routing/recommend");
    assert.match(calls[1].url, /\/rest\/v1\/rpc\/find_nearest_chargers$/);
  });
});
