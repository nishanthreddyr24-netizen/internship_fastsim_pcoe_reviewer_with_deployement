# Test Results

Last recorded local verification: 2026-05-29

## SOC-Aware Multi-Stop Planner Tests

Command:

```bash
python -m pytest tests\test_multi_stop_planner.py tests\test_routing_plan_endpoint.py -vv
```

Output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.8, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\R Nishanth Reddy\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\R Nishanth Reddy\Downloads\fastsim-fastsim-3\fastsim-fastsim-3
configfile: pyproject.toml
plugins: anyio-4.8.0, langsmith-0.3.45
collecting ... collected 8 items

tests/test_multi_stop_planner.py::test_planner_reaches_destination_with_zero_stops PASSED [ 12%]
tests/test_multi_stop_planner.py::test_planner_adds_one_charging_stop_when_destination_depletes PASSED [ 25%]
tests/test_multi_stop_planner.py::test_planner_supports_two_charging_stops PASSED [ 37%]
tests/test_multi_stop_planner.py::test_planner_fails_when_no_charger_is_reachable PASSED [ 50%]
tests/test_multi_stop_planner.py::test_planner_respects_max_charging_stops PASSED [ 62%]
tests/test_multi_stop_planner.py::test_planner_uses_fallback_charger_power_when_catalog_power_missing PASSED [ 75%]
tests/test_multi_stop_planner.py::test_planner_selects_lowest_p_fail_reachable_charger PASSED [ 87%]
tests/test_routing_plan_endpoint.py::test_routing_plan_endpoint_returns_planner_response PASSED [100%]

============================= 8 passed in 19.11s ==============================
```

These cover:

- zero-stop success
- one charging stop
- two charging stops
- no reachable charger
- max charging stops exceeded
- fallback charger power
- lowest `p_fail` charger selection
- endpoint response

## Full Test Suite

Command:

```bash
python -m pytest tests -q
```

Output:

```text
.................................................                        [100%]
49 passed in 24.86s
```
