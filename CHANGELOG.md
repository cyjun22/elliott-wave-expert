# CHANGELOG

## [2.2.0] - 2026-04-08

### 📊 Wave Chart (봉차트 파동 카운트)
- `wave_chart.py` 신규 생성: 캔들스틱 차트 + 파동 카운트 시각화 모듈
- **캔들스틱**: 다크 테마, 상승(초록)/하락(빨간) 봉 차트
- **파동 라벨**: 원형 배지 (파동별 고유 색상) + 가격 태그
- **연결선**: 파동별 색상 구분 지그재그 라인
- **거래량 서브플롯**: 상승/하락 색상 구분
- **무효화 레벨 / 목표가 영역**: 선택적 표시
- **대안 시나리오 오버레이**: 반투명 파동 카운트 중첩
- `WaveAnalysis` 객체에서 자동 파동 추출 + 수동 파동 지정 둘 다 지원
- 내장 BTC 샘플 데이터 (2022-2025 합성 OHLCV)
- CLI: `python wave_chart.py --sample | --csv FILE [-o PATH]`
- 테스트 19개 추가 (`tests/test_wave_chart.py`)

## [2.1.0] - 2026-04-08

### 📊 Report Generator
- `report_generator.py` 신규 생성: 일관된 시각적 HTML 보고서 생성 모듈
- **Quality Score Ring**: 독스트링 커버리지 + 테스트 통과율 + 패턴 구현율 + 보안 이슈 기반 종합 점수 (0-100)
- **KPI Dashboard**: 6개 핵심 지표 카드 (파일 수, 총 라인, 클래스, 함수, 패턴, 테스트)
- **Pattern Grid**: 12종 패턴별 구현/테스트 상태 시각화
- **Module Architecture Map**: 6개 그룹 시각화 (Core, Tracking, AI/LLM, Multi-agent, Visualization, Execution)
- **File Metrics Table**: 파일별 라인 수 + 크기 바 + 독스트링 비율
- **Git History**: 커밋별 insertions/deletions 통계
- **Security Scan**: bare except, SQL injection, eval/exec 자동 탐지
- CLI 지원: `python report_generator.py [-o PATH] [--json] [--root DIR]`
- `__main__.py` 업데이트: `python -m elliott report` 커맨드 추가
- 테스트 22개 추가 (`tests/test_report.py`): 수집기, 렌더러, 통합, 일관성 검증

## [2.0.0] - 2026-04-08

### 🏗️ Architecture (Breaking)
- `wave_tracker.py` (1,936줄) → `wave_scenarios.py` + `wave_visualization.py` + `wave_tracker.py` (643줄)로 분리
- 하위 호환성 유지: `wave_tracker`에서 re-export 보장, 외부 import 변경 불필요
- `llm_utils.py` 신규 생성: 공유 LLM 클라이언트 싱글턴 + JSON 파싱 유틸리티

### ✅ Pattern Recognition (9 new patterns)
- 신규 구현: Leading Diagonal, Ending Diagonal, Double Zigzag, Triple Zigzag
- 신규 구현: Expanded Flat, Running Flat, Triangle, Complex (WXY/WXYXZ), Unknown
- 합계: **12/12 패턴 완전 구현** (v1.x: 3/12)
- `patterns.py` 328줄 → 1,071줄
- 공유 Fibonacci 헬퍼 추출: `_retrace_ratio()`, `_in_fib_range()`, `_waves_overlap()`, `_progressive_narrowing()`
- 파동 레이블 표준화: 0-인덱스 → 1-인덱스 (`"1"` ~ `"5"`)

### 🎯 Scenario Invalidation System
- `ScenarioWithInvalidation` 데이터클래스 도입
- 가격 기반 무효화 레벨 (`invalidation_price`, `invalidation_direction`)
- 시간 기반 만료 (`valid_until`: 조정 90일, 충격 120일)
- 모든 시나리오에 `falsifiable_condition` 사람이 읽을 수 있는 반증 조건 문자열 포함
- `is_invalidated(price)` / `is_expired()` 메서드

### 🔧 Bug Fixes & Security
- **SQL Injection 수정** (`tracker_history.py`): f-string → parameterized queries
- **NameError 수정** (`multi_timeframe_validator.py`): `w3_move = 0` 초기화 + 0 나누기 방지
- **DataFrame 변이 수정** (`hybrid_expert.py`): `df.copy()` 추가
- **tempfile 레이스 컨디션** (`chart_renderer.py`): `mktemp()` → `NamedTemporaryFile()`
- **Bare except 수정** (`retroactive_adjuster.py`): `except:` → `except (JSONDecodeError, IOError, OSError):`
- **Import 실패 로깅** (`__init__.py`): silent pass → `_logger.warning()`

### 🧪 Testing (70 tests, 100% pass rate)
- `tests/conftest.py`: 공유 픽스처 (Pivot/Wave/OHLCV 팩토리)
- `tests/test_patterns.py`: 12 패턴 유형 전체 (20개 테스트)
- `tests/test_core.py`: 방향/검증/사이클 감지 (17개 테스트)
- `tests/test_scenarios.py`: 무효화, 만료, 시나리오 생성기 (14개 테스트)
- `tests/test_validation.py`: 규칙 위반, 신뢰도 페널티, 무효화 레벨 (19개 테스트)

### 📚 RAG Pattern Database
- 역사적 패턴 DB: 5개 → **20개** 확장
- 커버리지: BTC, ETH, SPX, GOLD, TSLA, NI225, DJIA (7개 자산군)
- 패턴 유형: impulse, extended 5th, ending diagonal, leading diagonal, zigzag, double zigzag, expanded flat, running flat, triangle, complex WXY, triple zigzag (10종)
- 각 항목: `fib_ratios`, `volume`, `market_condition`, `failure_mode`, `notes` 포함
- 실패 사례 포함: triangle breakdown, truncated 5th, 34년 조정

### 🔧 LLM Integration
- `llm_utils.py`: 공유 AzureOpenAI 클라이언트 싱글턴 (`get_shared_azure_client()`)
- `llm_utils.py`: `safe_parse_json()` — 3단계 폴백 JSON 파싱 (코드블록, 직접, 수리)
- `LLMUsageTracker`: 토큰/비용 추적
- `dual_agent_expert.py`: 공유 클라이언트 + 공유 JSON 파싱으로 전환

### ⚙️ Core Improvements
- **방향 감지** (`core.py`): 단순 가격 비교 → 20기간 SMA slope
- **사이클 감지** (`core.py`): 균등 분할 → Fibonacci 비율 (`1:0.618:1.618:0.618:1`)
- **입력 검증** (`core.py`): `_validate_input_data()` — 최소 30 캔들, NaN, 중복, 극단 변동
- **확률 엔진** (`scenario_tree.py`): 설정 가능한 베이지안 멀티플라이어
- **시나리오 상수** (`adaptive_tracker.py`): `ScenarioType` 클래스
- **클러스터 강도** (`strategy_executor.py`): 확률 가중 합산
- **서브파동 방향** (`subwave_analyzer.py`): 레이블 기반 → 실제 가격 기반

---

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

---

## 2026-04-09 — God Object Refactoring: wave_tracker.py

### ARCHITECTURAL REFACTORING

Split the 1,936-line `wave_tracker.py` god object into 3 focused modules:

#### A. New `wave_scenarios.py` (757 lines)
- **`WaveInterpretation`** dataclass: Per-scenario wave labels, projected paths, targets, invalidation
- **`ScenarioWithInvalidation`** dataclass: Wraps scenarios with `invalidation_price`, `invalidation_direction`, `valid_until`, `falsifiable_condition`, plus `is_invalidated()` and `is_expired()` methods
- **`ScenarioGenerator`** class: All scenario generation logic including `generate_from_analysis()`, `generate_interpretations()`, `_calculate_dynamic_probability()`, `_detect_abc_position()`, and all `_create_*_scenario()` / `_interpret_*()` methods

#### B. New `wave_visualization.py` (631 lines)
- **`WaveVisualizer`** class: Takes a tracker reference, exposes all chart methods
  - `get_scenario_chart()`: Scenario path visualization
  - `get_multi_timeframe_chart()`: Multi-timeframe chart
  - `create_quadrant_chart()`: 2x2 grid summary
  - `generate_scenario_charts()`: Individual scenario charts with future projections
  - `analyze_and_visualize()`: Full analysis + visualization pipeline
  - `_add_scenario_projections()`: Extracted projection logic by scenario type
  - `_draw_future_candles()`: Extracted future candlestick rendering

#### C. Slimmed `wave_tracker.py` (643 lines, down from 1,936)
- Keeps only core `WaveTracker` class: `__init__`, `initialize`, `update`, `get_tracking_result`, `get_report`, history/statistics, self-correction, retroactive adjustment
- **Backward compatibility**: Re-exports `WaveInterpretation`, `ScenarioWithInvalidation`, `ScenarioGenerator` from `wave_scenarios`
- **Delegation methods**: `get_scenario_chart()`, `get_multi_timeframe_chart()`, `create_quadrant_chart()`, `generate_scenario_charts()`, `analyze_and_visualize()` delegate to `WaveVisualizer`
- No import changes required in other files

#### D. Improved Invalidation System in `generate_dynamic_scenarios()`
- Now returns `List[ScenarioWithInvalidation]` instead of `List[Dict]`
- Each scenario wrapped with:
  - **Bearish/correction scenarios**: Invalidated if price exceeds recent high × 1.02 (above), valid 90 days
  - **Bullish/impulse scenarios**: Invalidated if price drops below recent low × 0.98 (below), valid 120 days
  - **Flat scenarios**: Invalidated if price exceeds Wave A start × 1.03 (above), valid 90 days
- Uses 60-bar lookback for recent high/low calculation
- Human-readable `falsifiable_condition` string on each wrapped scenario

### Files Modified
| File | Changes |
|------|---------|
| `wave_tracker.py` | Reduced from 1,936 to 643 lines; core tracker + backward compat re-exports + delegation |

### Files Created
| File | Purpose |
|------|---------|
| `wave_scenarios.py` | Scenario generation engine (WaveInterpretation, ScenarioWithInvalidation, ScenarioGenerator) |
| `wave_visualization.py` | Chart visualization engine (WaveVisualizer class) |

---

## 2026-04-09 — Full Pattern Recognition + RAG Database Expansion

### patterns.py — All 12 Pattern Types Implemented (328→1071 lines)

**9 new pattern checkers added to `PatternRecognizer`:**

| Method | Pattern | Min Pivots | Confidence Range |
|--------|---------|------------|-----------------|
| `_check_leading_diagonal` | 선행 대각선 | 6 | 0.55-0.75 |
| `_check_ending_diagonal` | 종결 대각선 | 6 | 0.60-0.80 |
| `_check_double_zigzag` | 이중 지그재그 (WXY) | 8 | 0.50-0.70 |
| `_check_triple_zigzag` | 삼중 지그재그 (WXYXZ) | 12 | 0.40-0.60 |
| `_check_expanded_flat` | 확장형 플랫 | 4 | 0.55-0.75 |
| `_check_running_flat` | 러닝 플랫 | 4 | 0.50-0.65 |
| `_check_triangle` | 삼각형 (ABCDE) | 6 | 0.55-0.75 |
| `_check_complex` | 복합 조정 (WXY/WXYXZ) | 8 | 0.40-0.60 |
| `_check_unknown` | 미확정 (catch-all) | 1 | 0.20 |

**Other changes:**
- `recognize()` refactored to loop through all 11 checkers + unknown fallback
- `_check_flat()` now returns only Regular Flat; Expanded/Running handled by dedicated methods
- `get_pattern_description()` expanded to cover all 12 PatternType values
- Shared Fibonacci helpers extracted: `_retrace_ratio()`, `_in_fib_range()`, `_waves_overlap()`, `_progressive_narrowing()`

### pattern_rag.py — RAG Database Expanded (5→20 patterns)

**15 new historical patterns added covering:**
- 7 asset classes: BTC, ETH, SPX, GOLD, TSLA, NI225, DJIA
- 10 pattern types: impulse, extended 5th, ending diagonal, leading diagonal, zigzag, double zigzag, expanded flat, running flat, triangle, complex WXY, triple zigzag
- Rich metadata: `fib_ratios`, `volume`, `market_condition`, `failure_mode`, `notes`
- Failure modes documented: triangle breakdown, truncated 5th, 34-year correction

| Pattern ID | Symbol | Type | Outcome |
|-----------|--------|------|---------|
| `gold_2001_2011` | GOLD | Extended 5th | extended_5th |
| `tsla_2020_2021` | TSLA | Extended 5th | extended_5th |
| `spx_2018_ending_diag` | SPX | Ending Diagonal | abc_correction |
| `btc_2019_leading_diag` | BTC | Leading Diagonal | new_supercycle |
| `btc_2022_zigzag` | BTC | Zigzag | abc_correction |
| `spx_2020_covid_zigzag` | SPX | Zigzag | abc_correction |
| `eth_2022_double_zigzag` | ETH | Double Zigzag | abc_correction |
| `spx_2015_expanded_flat` | SPX | Expanded Flat | abc_correction |
| `spx_2014_running_flat` | SPX | Running Flat | new_supercycle |
| `btc_2019_triangle` | BTC | Triangle | abc_correction (failed) |
| `gold_2013_triangle` | GOLD | Triangle | abc_correction |
| `spx_2000_2003_complex` | SPX | Complex WXY | abc_correction |
| `nikkei_1989_truncation` | NI225 | Impulse | abc_correction |
| `djia_1966_1974_triple_zz` | DJIA | Triple Zigzag | abc_correction |
