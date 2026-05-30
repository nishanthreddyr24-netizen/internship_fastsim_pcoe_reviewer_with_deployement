"use strict";

const http = require("node:http");

const DEFAULT_PORT = 3000;
const DEFAULT_PYTHON_ENGINE_URL = "http://fastsim:8000";
const DEFAULT_SUPABASE_RPC = "find_nearest_chargers";
const DEFAULT_SEARCH_RADIUS_METERS = 25000;
const DEFAULT_VALHALLA_HEALTH_TIMEOUT_MS = 1000;

class ApiError extends Error {
  constructor(statusCode, message, details = undefined) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.details = details;
  }
}

function jsonResponse(res, statusCode, body) {
  const payload = JSON.stringify(body);
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function parseJson(buffer) {
  if (buffer.length === 0) {
    return {};
  }
  try {
    return JSON.parse(buffer.toString("utf8"));
  } catch (error) {
    throw new ApiError(400, "request body must be valid JSON", error.message);
  }
}

function requiredNumber(body, key) {
  const value = Number(body[key]);
  if (!Number.isFinite(value)) {
    throw new ApiError(400, `${key} is required and must be a number`);
  }
  return value;
}

function requiredObject(body, key) {
  const value = body[key];
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ApiError(400, `${key} is required and must be an object`);
  }
  return value;
}

function mapLegacyRequest(body, env = process.env) {
  if (!body.vehicle_id || typeof body.vehicle_id !== "string") {
    throw new ApiError(400, "vehicle_id is required and must be a string");
  }

  const searchRadiusMeters = Number(
    body.search_radius_meters ||
      env.SUPABASE_SEARCH_RADIUS_METERS ||
      DEFAULT_SEARCH_RADIUS_METERS,
  );
  const chargerRadiusKm = Number(body.charger_radius_km || searchRadiusMeters / 1000);

  return {
    vehicle_id: body.vehicle_id,
    start: {
      lat: requiredNumber(body, "start_lat"),
      lon: requiredNumber(body, "start_lon"),
    },
    end: {
      lat: requiredNumber(body, "end_lat"),
      lon: requiredNumber(body, "end_lon"),
    },
    environment: requiredObject(body, "environment"),
    vehicle_state: requiredObject(body, "vehicle_state"),
    costing: body.costing || "auto",
    charger_radius_km: chargerRadiusKm,
    charger_limit: Number(body.charger_limit || 5),
    compatible_only: body.compatible_only !== false,
    include_charger_routes: body.include_charger_routes !== false,
  };
}

async function requestJson(fetchImpl, method, url, body = undefined, headers = {}) {
  const response = await fetchImpl(url, {
    method,
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      payload = { raw: text };
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, `upstream request failed: ${url}`, payload);
  }
  return payload || {};
}

async function fetchWithTimeout(fetchImpl, url, options = {}, timeoutMs = 1000) {
  const controller = new AbortController();
  let timeout;
  const timeoutPromise = new Promise((_resolve, reject) => {
    timeout = setTimeout(() => {
      controller.abort();
      reject(new Error(`request timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
  try {
    return await Promise.race([
      fetchImpl(url, { ...options, signal: controller.signal }),
      timeoutPromise,
    ]);
  } finally {
    clearTimeout(timeout);
  }
}

function normalizeSupabaseRows(rows) {
  return Array.isArray(rows) ? rows : [];
}

async function fetchSupabaseChargers(coordinate, env, fetchImpl) {
  if (!coordinate) {
    return { rows: [], source: "local_fallback_no_depletion" };
  }
  if (!env.SUPABASE_URL || !env.SUPABASE_KEY) {
    return { rows: [], source: "local_fallback_supabase_unconfigured" };
  }

  const rpcName = env.SUPABASE_RPC_NAME || DEFAULT_SUPABASE_RPC;
  const baseUrl = env.SUPABASE_URL.replace(/\/+$/, "");
  const radius = Number(env.SUPABASE_SEARCH_RADIUS_METERS || DEFAULT_SEARCH_RADIUS_METERS);
  const payload = {
    deplete_lat: coordinate.lat,
    deplete_lng: coordinate.lon,
    search_radius_meters: radius,
  };

  try {
    const rows = await requestJson(
      fetchImpl,
      "POST",
      `${baseUrl}/rest/v1/rpc/${rpcName}`,
      payload,
      {
        apikey: env.SUPABASE_KEY,
        Authorization: `Bearer ${env.SUPABASE_KEY}`,
        Prefer: "return=representation",
      },
    );
    const normalizedRows = normalizeSupabaseRows(rows);
    return normalizedRows.length > 0
      ? { rows: normalizedRows, source: "supabase" }
      : { rows: [], source: "local_fallback_supabase_empty" };
  } catch (error) {
    return {
      rows: [],
      source: "local_fallback_supabase_error",
      error: error.details || error.message,
    };
  }
}

function mapLegacyResponse(routingResponse, chargerLookup) {
  const localChargers = routingResponse.recommended_chargers || [];
  const supabaseRows = chargerLookup.rows || [];
  const chargers = supabaseRows.length > 0 ? supabaseRows : localChargers;

  return {
    status: "success",
    simulation: routingResponse.simulation,
    route_edges: routingResponse.primary_route_edges || routingResponse.route_edges || [],
    chargers,
    charger_source: supabaseRows.length > 0 ? "supabase" : chargerLookup.source,
    charger_fallback_error: chargerLookup.error,
  };
}

async function handleLegacyRoute(req, res, config) {
  const body = parseJson(await readBody(req));
  const pythonPayload = mapLegacyRequest(body, config.env);
  const routingResponse = await requestJson(
    config.fetchImpl,
    "POST",
    `${config.pythonEngineUrl}/api/v1/routing/recommend`,
    pythonPayload,
  );
  const depletionCoordinate = routingResponse.simulation
    ? routingResponse.simulation.depletion_coordinate
    : null;
  const chargerLookup = await fetchSupabaseChargers(
    depletionCoordinate,
    config.env,
    config.fetchImpl,
  );
  jsonResponse(res, 200, mapLegacyResponse(routingResponse, chargerLookup));
}

async function proxyToPython(req, res, pathname, search, config) {
  const body = await readBody(req);
  const headers = {};
  if (req.headers["content-type"]) {
    headers["Content-Type"] = req.headers["content-type"];
  }
  const response = await config.fetchImpl(`${config.pythonEngineUrl}${pathname}${search}`, {
    method: req.method,
    headers,
    body: body.length === 0 || req.method === "GET" || req.method === "HEAD" ? undefined : body,
  });
  const responseBody = Buffer.from(await response.arrayBuffer());
  const responseHeaders = {
    "Content-Type": response.headers.get("content-type") || "application/octet-stream",
    "Content-Length": responseBody.length,
  };
  res.writeHead(response.status, responseHeaders);
  res.end(responseBody);
}

async function handleHealth(_req, res, config) {
  const checks = { node: "ok", python: "unknown", runtime: "unknown", valhalla: "not_configured" };
  let statusCode = 200;

  try {
    await requestJson(config.fetchImpl, "GET", `${config.pythonEngineUrl}/health`);
    checks.python = "ok";
    const runtime = await requestJson(
      config.fetchImpl,
      "GET",
      `${config.pythonEngineUrl}/diagnostics/runtime`,
    );
    checks.runtime = runtime.simulation_engine || "unknown";
  } catch (error) {
    checks.python = "unavailable";
    checks.python_error = error.details || error.message;
    statusCode = 503;
  }

  if (config.valhallaUrl) {
    try {
      await fetchWithTimeout(
        config.fetchImpl,
        `${config.valhallaUrl.replace(/\/+$/, "")}/status`,
        { method: "GET" },
        config.valhallaHealthTimeoutMs,
      );
      checks.valhalla = "reachable";
    } catch (error) {
      checks.valhalla = "unreachable";
      checks.valhalla_error = error.message;
    }
  }

  jsonResponse(res, statusCode, {
    status: statusCode === 200 ? "ok" : "degraded",
    checks,
  });
}

function createServer(options = {}) {
  const env = options.env || process.env;
  const config = {
    env,
    fetchImpl: options.fetchImpl || global.fetch,
    pythonEngineUrl: (env.PYTHON_ENGINE_URL || DEFAULT_PYTHON_ENGINE_URL).replace(/\/+$/, ""),
    valhallaUrl: env.VALHALLA_URL || "",
    valhallaHealthTimeoutMs: Number(
      env.VALHALLA_HEALTH_TIMEOUT_MS || DEFAULT_VALHALLA_HEALTH_TIMEOUT_MS,
    ),
  };

  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");
      if (req.method === "GET" && url.pathname === "/health") {
        await handleHealth(req, res, config);
        return;
      }
      if (req.method === "POST" && url.pathname === "/api/calculate-ev-route") {
        await handleLegacyRoute(req, res, config);
        return;
      }
      if (url.pathname.startsWith("/api/v1/") || url.pathname.startsWith("/diagnostics/")) {
        await proxyToPython(req, res, url.pathname, url.search, config);
        return;
      }
      jsonResponse(res, 404, { detail: "not found" });
    } catch (error) {
      if (error instanceof ApiError) {
        jsonResponse(res, error.statusCode, { detail: error.message, upstream: error.details });
        return;
      }
      jsonResponse(res, 500, { detail: error.message || "internal server error" });
    }
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT || DEFAULT_PORT);
  createServer().listen(port, "0.0.0.0", () => {
    console.log(`EV routing orchestrator listening on ${port}`);
  });
}

module.exports = {
  ApiError,
  createServer,
  fetchSupabaseChargers,
  mapLegacyRequest,
  mapLegacyResponse,
};
