# FASTSim PCoE Charger Reviewer

This repository combines a FASTSim-backed EV route simulation with charger metadata, charger review confidence scoring, and NASA PCoE battery-aging data. The goal is to estimate battery drain along a route, detect a low-SOC panic point, and rank nearby chargers with clear assumptions.

The project is built on top of NREL FASTSim 3. The added work in this repo lives mainly in `app/`, `tests/`, and the generated analysis files in the repository root.

## What This Project Does

1. Converts `route_edges.json` into a 1 Hz FASTSim drive cycle.
2. Looks up a vehicle from `vehicles_enrichment_GLOBAL_20260517_0915.csv`.
3. Runs FASTSim to produce a second-by-second SOC timeline.
4. Detects the first coordinate where SOC crosses a safety buffer.
5. Normalizes New Delhi charger data from `new_delhi_chargers.json` and `new_delhi_chargers.csv`.
6. Uses PCoE battery aging data as state-of-health scenarios.
7. Scores charger confidence from review sentiment, explicit ratings, OCPI-style status, and equipment age.

## Important Outputs

Generated output files:

- `route_edges_fastsim_result.json`: FASTSim route result for the normal route.
- `battery_drainage_array.json`: per-second coordinate and battery percentage array.
- `depletion_check_15pct.json`: normal-run 15 percent buffer check.
- `depletion_test_15pct_result.json`: low-SOC depletion test result.
- `depletion_test_battery_drainage_array.json`: low-SOC drainage array.
- `depletion_test_panic_point_15pct.json`: exact panic-point coordinate for the low-SOC test.
- `normalized_new_delhi_chargers.csv`: deduplicated charger station metadata.
- `route_nearest_new_delhi_chargers.csv`: nearest compatible chargers to the route.
- `point_nearest_new_delhi_chargers.csv`: nearest chargers to start, destination, and panic point.
- `pcoe_battery_capacity_summary.csv`: battery-level PCoE capacity fade summary.
- `pcoe_discharge_cycles_summary.csv`: discharge-cycle-level PCoE summary.
- `pcoe_fastsim_route_scenarios.csv`: FASTSim route outputs under PCoE-derived SOH scenarios.
- `pcoe_charger_integrated_report.json`: combined summary report.

## FASTSim Route Physics

The route input is `route_edges.json`. Each edge includes:

- `distance_m`: route segment distance in meters.
- `speed_kph`: segment speed in km/h.
- `grade_pct`: road grade in percent.
- `start_coordinate` and `end_coordinate`: latitude/longitude endpoints.

The bridge in `app/physics/cycle_bridge.py` converts these into FASTSim units:

- speed: `speed_kph / 3.6` to meters per second
- grade: `grade_pct / 100.0`
- ambient temperature: `ambient_temp_c + 273.15` Kelvin

FASTSim then solves the vehicle powertrain second by second and outputs cumulative battery energy. The app converts that into SOC:

```text
soc[t] = starting_soc - energy_out_joules[t] / effective_capacity_joules
```

The current primary route simulation uses:

```text
Vehicle: Mahindra Electric BE 6
Vehicle ID: IN-2025-0007
Usable battery: 55.3 kWh
Starting SOC: 80%
Safety buffer: 15%
Ambient temperature: 25 C
Battery SOH: scenario-dependent
```

## Battery Drainage Array

`battery_drainage_array.json` is the route-by-route battery output. Each point contains:

- `second`
- `edge_index`
- `lat`
- `lon`
- `cumulative_distance_m`
- `soc_fraction`
- `battery_pct`
- `delta_soc_fraction`
- `regen_or_gain`

This is the "battery drainage array" used to determine where the vehicle crosses a safety threshold.

## Panic Point / Depletion Check

The panic-point algorithm scans the SOC timeline in order:

```text
for each route point:
    if soc_fraction <= protection_soc:
        return this coordinate as the panic point
```

For the low-SOC demonstration:

```text
Starting SOC: 16%
Protection SOC: 15%
Panic second: 299
Panic coordinate: 28.573083871, 77.059320968
Battery at crossing: 14.9998%
Distance at crossing: 3831.992 m
```

## PCoE Battery Aging Usage

The PCoE data comes from NASA battery aging archives under:

```text
5.+Battery+Data+Set/5. Battery Data Set/
```

The raw `.zip` archives are ignored by git, but the derived summaries are committed.

The PCoE files contain lab cell charge, discharge, and impedance cycles. The integration extracts discharge capacities from `.mat` files and computes:

```text
soh_vs_initial = discharge_capacity_ah / first_discharge_capacity_ah
soh_vs_2ah_rated = discharge_capacity_ah / 2.0
```

Those values are used as pack-level SOH stress-test scenarios:

- fresh pack: `SOH = 1.0`
- PCoE median final SOH: about `0.9515`
- PCoE EOL-style scenario: `SOH = 0.70`

Important caveat: PCoE is lab cell data. It is not direct Mahindra BE 6 pack telemetry. In this project it is used as a degradation proxy to test how route outputs change when available battery capacity is reduced.

## Thermal Capacity Correction

Battery usable capacity is corrected by both SOH and ambient temperature in `app/physics/battery.py`:

```text
effective_kwh = usable_kwh * state_of_health * thermal_factor
```

The thermal factor is:

```text
if ambient_temp_c >= 25:
    thermal_factor = 1.0
elif ambient_temp_c <= -25:
    thermal_factor = 0.58
else:
    thermal_factor = -0.000114*T^2 + 0.005720*T + 0.924
```

The factor is clamped to `[0.58, 1.0]`.

Example values:

```text
-25 C -> 0.5800
-10 C -> 0.8554
  0 C -> 0.9240
 25 C -> 1.0000
```

## PCoE Scenario Results

From `pcoe_fastsim_route_scenarios.csv`:

```text
Fresh 100% SOH:
Final SOC: 78.1089%
SOC drop: 1.8911 percentage points
Energy used: 1.0458 kWh
Consumption: 124.70 Wh/km

PCoE median final SOH, 95.15%:
Final SOC: 78.0126%
SOC drop: 1.9874 percentage points
Energy used: 1.0458 kWh
Consumption: 124.70 Wh/km

EOL-style 70% SOH:
Final SOC: 77.2984%
SOC drop: 2.7016 percentage points
Energy used: 1.0458 kWh
Consumption: 124.70 Wh/km
```

The energy required to drive the route remains roughly the same, but the SOC percentage drop increases as usable battery capacity decreases.

## Charger Metadata Normalization

New Delhi charger data is read from:

- `new_delhi_chargers.json`
- `new_delhi_chargers.csv`

The normalizer deduplicates stations by PlugShare location ID and merges connector metadata. It classifies BE 6 compatibility using:

```text
compatible = station has CCS2 or Type 2 connector
```

Current normalized summary:

```text
Unique stations: 28
BE 6-compatible stations: 24
Stations with known nonzero power: 3
```

The nearest route charger in the generated output is:

```text
Haridwar (Coming Soon)
Distance to route: 8.53 km
Connector: CCS2
Power: unknown in source data
Reviews: 0
```

Best reviewed nearby candidate:

```text
A2, Commercial Complex Opp Jwala Heri Market
Distance to route start: 10.34 km
Connectors: CCS2, Type 2
Reviews: 15
Power: unknown in source data
```

## Review Confidence System

The charger confidence service is implemented in `app/confidence/service.py`. It loads review data from:

```text
india_ev_reviews.xlsx
sheet: india_ev_reviews
```

For each station, the system computes:

1. review sentiment
2. time-decayed review weight
3. average weighted sentiment
4. failure probability
5. confidence score

### Sentiment Score

If a review has a text comment, the service uses:

```text
distilbert-base-uncased-finetuned-sst-2-english
```

The model returns positive or negative sentiment. The project converts it to positive sentiment probability:

```text
if label == NEGATIVE:
    sentiment = 1.0 - model_score
else:
    sentiment = model_score
```

If no comment exists, the rating fallback is:

```text
rating =  1 -> sentiment = 0.85
rating = -1 -> sentiment = 0.15
rating =  0 or missing -> sentiment = 0.50
```

### Time Decay

Recent reviews matter more. The decay half-life is 30 days:

```text
weight = exp(-(ln(2) / 30) * age_days)
```

Weighted average sentiment:

```text
average_sentiment = sum(sentiment_i * weight_i) / sum(weight_i)
```

### Failure Probability

Failure probability is calculated with a logistic model:

```text
x_ocpi = 0 if ocpi_status == AVAILABLE else 1
x_sentiment_penalty = 1 - average_sentiment
x_age = max(0, equipment_age_days)

p_fail = sigmoid(
    2.15 * x_ocpi
  + 1.65 * x_sentiment_penalty
  + 0.006 * x_age
  - 1.45
)
```

where:

```text
sigmoid(x) = 1 / (1 + exp(-x))
```

The confidence score is:

```text
confidence = 1.0 - p_fail
```

### What The Probability Means

`p_fail` is a heuristic probability that a charger may fail or be unreliable. It combines:

- real-time or supplied OCPI-like status
- recent user review sentiment
- equipment age

It should be treated as a prototype reliability score, not as a certified ground-truth failure probability.

## API Endpoints

The app exposes:

```text
GET  /health
POST /api/v1/physics/simulate
GET  /api/v1/confidence/stations/{station_id}
GET  /api/v1/confidence/nearby
POST /api/v1/confidence/rank
```

The simulation endpoint accepts:

```json
{
  "vehicle_id": "IN-2025-0007",
  "environment": {"ambient_temp_c": 25.0},
  "starting_soc": 0.8,
  "protection_soc": 0.15,
  "route_edges": []
}
```

## PluginAny Routing Integration

The upgraded PluginAny protocol is implemented as an offline-first integration test path for route physics, weather inputs, Valhalla-style route edges, and vehicle database properties.

New simulation request fields:

- `environment.wind_speed_kph`
- `environment.wind_direction_deg`
- `environment.precipitation_mm`
- `route_edges[].heading_deg`
- `route_edges[].wind_direction_deg`
- `vehicle_state.starting_soc`
- `vehicle_state.protection_soc`
- `vehicle_state.hvac_power_kw`
- `vehicle_state.adjusted_rr_coef`

The endpoint remains backward compatible with top-level `starting_soc` and `protection_soc`.

Current offline behavior:

- Route validation uses `route_edges.json` as the local Valhalla-style fixture.
- Weather tests use synthetic or mocked weather data; live weather calls are optional and use a configurable API key.
- FASTSim is loaded from the local repo package in `python/fastsim`.
- Missing vehicle rolling resistance falls back to `0.012` and logs a backend warning.
- Heavy rain above `2.0 mm/hr` applies the default wet-road rolling resistance multiplier of `1.15`.
- HVAC load is estimated from ambient temperature or taken from `vehicle_state.hvac_power_kw`.
- Headwind drag uses edge heading and wind direction instead of simply adding wind speed to vehicle speed.

The PDF worst-case payload now returns `200 OK` with `status: depletion_triggered` under local FASTSim plus the conservative environmental bridge adjustment.

## Running Tests

Focused app tests:

```bash
python -m pytest tests -q
```

At the time this README was written, those tests passed locally:

```text
30 passed
```

## Validation Notes

This repo verifies the software pipeline, not real-world physical accuracy.

Verified locally:

- FASTSim package loads from the local repo.
- route JSON validates against the app schema.
- SOC timeline aligns with route points.
- depletion check extracts the first buffer-crossing coordinate.
- generated JSON and CSV files parse successfully.
- charger metadata is deduplicated by station ID.

Not yet fully validated:

- FASTSim output against real BE 6 trip telemetry.
- review sentiment against actual charger outage logs.
- PCoE cell aging against BE 6 pack aging.
- New Delhi charger power values, because most source records have `0.0 kW` or missing power.

For a field-valid comparison, collect:

- actual start/end SOC
- GPS trace
- speed trace
- elevation/grade
- ambient temperature
- payload
- vehicle trim and tire setup
- BMS energy used
- charger actual availability/session status

## Upstream FASTSim Credit

This project is based on NREL FASTSim 3. FASTSim is a vehicle energy simulation framework from the National Renewable Energy Laboratory.

Original project:

```text
https://github.com/NREL/fastsim
```
