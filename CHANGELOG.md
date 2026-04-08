# CHANGELOG

## 2026-04-08 — Security Fixes, Bug Fixes, and Architectural Improvements

### HIGH PRIORITY FIXES (Security & Bugs)

#### 1. SQL Injection Fix — `tracker_history.py`
- **Lines 219-226, 252-270**: Replaced f-string interpolation (`f" WHERE symbol = '{symbol}'"`) with parameterized queries (`WHERE symbol = ?` with `params` list)
- Both `get_training_data()` and `get_scenario_accuracy()` now use safe parameterized queries via `pd.read_sql_query(..., params=)` and `conn.execute(query, params)`

#### 2. NameError Fix — `multi_timeframe_validator.py`
- **Line 261**: Initialized `w3_move = 0` before the conditional block that may or may not set it
- **Line 267**: Added guard `w3_move != 0` to prevent using uninitialized zero in comparison

#### 3. DataFrame Mutation Fix — `hybrid_expert.py`
- **Line 202**: Added `df = df.copy()` at the start of `_get_cycle_estimate()` to prevent in-place modification of the caller's DataFrame

#### 4. Deprecated tempfile Fix — `chart_renderer.py`
- **Lines 126-128, 284-286**: Replaced `tempfile.mktemp(suffix='.png')` with `tempfile.NamedTemporaryFile(suffix='.png', delete=False)` to eliminate race condition vulnerability

#### 5. Bare Except Fix — `retroactive_adjuster.py`
- **Line 78**: Changed `except:` to `except (json.JSONDecodeError, IOError, OSError):` to avoid catching `SystemExit`, `KeyboardInterrupt`, etc.

#### 6. Silent Import Failure Fix — `__init__.py`
- Added `import logging` and `_logger` at module level
- Changed bare `except ImportError: pass` to `except ImportError as e:` with `_logger.warning()` call for visibility when hybrid/LLM modules fail to load

---

### MEDIUM PRIORITY IMPROVEMENTS

#### 7. Shared LLM Utilities — New `llm_utils.py`
- Extracted `safe_parse_json()` from `dual_agent_expert.py` into a shared module
- Added `get_azure_openai_client()` factory function
- Added `get_shared_azure_client()` lazy singleton for connection reuse
- Other modules can now import from `llm_utils` instead of duplicating JSON parsing logic

#### 8. Shared LLM Client — `dual_agent_expert.py`
- Removed `from openai import AzureOpenAI` direct import
- Replaced per-method `AzureOpenAI(...)` instantiation in `validate_scenario()` and `correct_scenario()` with shared `get_shared_azure_client()` from `llm_utils.py`
- Removed the inline `_safe_parse_json()` function, now imports from `llm_utils`

#### 9. Wave Label Standardization — `patterns.py`
- Changed impulse wave labels from 0-indexed (`"0","1","2","3","4","5"`) to standard Elliott Wave convention (`"1","2","3","4","5"`)
- Wave objects now use labels `"1"` through `"5"` matching industry standard

#### 10. Direction Detection — `core.py`
- Replaced simplistic `close[-1] > close[0]` comparison with multi-period SMA slope detection
- Uses 20-period (or len/3) rolling SMA slope as primary signal
- Falls back to simple comparison when data is too short

#### 11. Input Data Quality Validation — `core.py`
- Added `_validate_input_data()` method checking: minimum candle count (30), missing values, duplicate timestamps, extreme price moves (>50%)
- Called at the start of `analyze()` to catch bad data early

#### 12. Fibonacci-Proportioned Cycle Detection — `core.py`
- Replaced equal-time-segment division in `auto_detect_cycle()` with Fibonacci-proportioned segments
- Ratios: `1 : 0.618 : 1.618 : 0.618 : 1` (total 4.854)
- Wave 3 segment now gets the largest time allocation, matching Elliott Wave theory

#### 13. Configurable Probability Engine — `scenario_tree.py`
- Added `DEFAULT_MULTIPLIERS` module-level dict with all Bayesian event multipliers
- `ProbabilityEngine.__init__()` now accepts optional `multipliers` parameter for calibration
- Multipliers accessed via `self.multipliers.get()` instead of class constants

#### 14. Scenario Name Constants — `adaptive_tracker.py`
- Added `ScenarioType` class with constants: `ABC_CORRECTION`, `EXTENDED_5TH`, `NEW_SUPERCYCLE`, `WAVE_5_IN_PROGRESS`
- Updated `_switch_scenario()` to use `ScenarioType.ABC_CORRECTION` and `ScenarioType.EXTENDED_5TH` instead of raw strings

#### 15. Validation Confidence Penalties — `validation.py`
- Guidelines in `_validate_impulse()` now apply graduated confidence penalties:
  - Wave 3 not longest: -5%
  - Wave 2 retracement outside 38.2-78.6%: -10%
  - Wave 3 momentum weaker than Wave 1: -10% (new check)
- Warning messages now include the penalty amount for transparency

#### 16. Confluence Probability Weighting — `strategy_executor.py`
- Price level collection now carries `probability` from parent scenario
- Cluster strength calculation uses probability-weighted sum instead of raw count
- Formula: `strength = min(1.0, prob_sum * 0.5 + type_count * 0.15)`

#### 17. Subwave Direction Detection — `subwave_analyzer.py`
- Replaced `is_upward = parent_wave in ['1', '3', '5']` with actual price-based direction check
- Now compares segment start/end close prices to determine direction
- Correctly handles bearish impulse patterns

---

### Files Modified
| File | Changes |
|------|---------|
| `__init__.py` | Import failure logging |
| `core.py` | Direction detection, input validation, Fibonacci segments |
| `patterns.py` | Wave label standardization (1-indexed) |
| `validation.py` | Guideline confidence penalties |
| `tracker_history.py` | SQL injection fix (parameterized queries) |
| `multi_timeframe_validator.py` | NameError fix (w3_move init) |
| `hybrid_expert.py` | DataFrame mutation fix |
| `chart_renderer.py` | tempfile security fix |
| `retroactive_adjuster.py` | Bare except fix |
| `dual_agent_expert.py` | Shared LLM client, shared JSON parsing |
| `scenario_tree.py` | Configurable probability multipliers |
| `adaptive_tracker.py` | ScenarioType constants |
| `strategy_executor.py` | Probability-weighted confluence scoring |
| `subwave_analyzer.py` | Price-based direction detection |

### Files Created
| File | Purpose |
|------|---------|
| `llm_utils.py` | Shared LLM utilities (JSON parsing, client management) |
| `CHANGELOG.md` | This file |
