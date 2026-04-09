# 아키텍처 문서 | Architecture Document

> Elliott Wave Expert — 모듈 의존성, 데이터 흐름, 설계 결정 기록

---

## 1. 모듈 의존성 맵 | Module Dependency Map

### 코어 레이어 (의존성 없음 or 최소 의존)

```
patterns.py
  └── (표준 라이브러리만: dataclasses, enum, datetime)

validation.py
  └── patterns.py

targets.py
  └── patterns.py

llm_utils.py
  └── openai (AzureOpenAI)
```

### 분석 레이어

```
core.py
  ├── patterns.py       (PatternType, PatternRecognizer, Wave, Pivot, WaveDirection, WaveDegree)
  ├── validation.py     (WaveValidator, ValidationResult)
  └── targets.py        (TargetCalculator, TargetLevel)
```

### 시나리오 레이어

```
wave_scenarios.py
  └── live_tracker.py   (WaveScenarioLive, WaveType, WavePosition, InvalidationRule, TargetLevel)

wave_visualization.py
  ├── wave_scenarios.py (WaveInterpretation, ScenarioWithInvalidation)
  └── scenario_chart.py (create_scenario_path_chart, create_multi_timeframe_chart)

wave_tracker.py
  ├── wave_scenarios.py        (WaveInterpretation, ScenarioWithInvalidation, ScenarioGenerator)
  ├── wave_visualization.py    (WaveVisualizer — 위임 패턴)
  ├── live_tracker.py          (MarketState, TrackingResult, ...)
  ├── scenario_tree.py         (ScenarioTree, ProbabilityEngine, FibonacciCalculator)
  ├── dual_agent_expert.py     (DualAgentExpert)
  ├── tracker_history.py       (WaveTrackerHistory)
  ├── scenario_chart.py        (create_scenario_path_chart, create_multi_timeframe_chart)
  └── retroactive_adjuster.py  (RetroactiveAdjuster, ScenarioGenerator, ConflictType)
```

### LLM 레이어

```
llm_validator.py
  └── llm_utils.py         (get_shared_azure_client, safe_parse_json)

dual_agent_expert.py
  └── llm_utils.py         (get_shared_azure_client, safe_parse_json)

hybrid_expert.py
  ├── core.py              (ElliottWaveAnalyzer)
  └── llm_validator.py     (LLMWaveValidator)

rag_expert.py
  ├── core.py
  ├── pattern_rag.py       (PatternRAGDatabase)
  └── llm_utils.py

multi_agent_system.py
  ├── dual_agent_expert.py
  ├── hybrid_expert.py
  └── rag_expert.py
```

### 유틸리티 레이어

```
data_validator.py    (독립 — OHLCV 입력 전처리)
tracker_history.py   (SQLite — 이력 영속화)
chart_renderer.py    (matplotlib — 차트 렌더링)
ai_strategist_report.py (보고서 생성)
strategy_executor.py
  └── wave_scenarios.py  (시나리오 신호 기반 매매 신호 계산)
```

---

## 2. 데이터 흐름 | Data Flow

원시 OHLCV 데이터에서 매매 신호까지의 전체 처리 흐름:

### Step 1: 입력 데이터 검증 (`data_validator.py` + `core.py`)

```
raw DataFrame (open, high, low, close, volume)
    │
    ├── data_validator.py: 스키마 / 타입 / 범위 검사
    │
    └── core._validate_input_data():
            - 최소 30개 캔들 확인
            - NaN 값 감지
            - 중복 타임스탬프 제거
            - 극단적 가격 변동 (>50%) 플래그
```

### Step 2: 방향 및 사이클 감지 (`core.py`)

```
validated DataFrame
    │
    ├── _detect_direction():
    │       20기간 SMA slope (양수 → UP, 음수 → DOWN)
    │       데이터 부족 시 close[-1] vs close[0] 단순 비교 폴백
    │
    └── auto_detect_cycle():
            피보나치 비율 분할: 1 : 0.618 : 1.618 : 0.618 : 1
            (5파 구조에서 W3가 가장 긴 시간 배분)
```

### Step 3: 피벗 감지 및 패턴 인식 (`core.py` + `patterns.py`)

```
direction + cycle data
    │
    ├── _detect_pivots():
    │       로컬 고/저점 감지 → List[Pivot] 생성
    │
    └── PatternRecognizer.recognize(pivots):
            11개 체커 순서대로 실행:
            impulse → leading_diagonal → ending_diagonal
            → zigzag → double_zigzag → triple_zigzag
            → flat → expanded_flat → running_flat
            → triangle → complex
            → unknown (catch-all)
            
            최고 신뢰도 패턴 반환 (PatternMatch)
```

### Step 4: 파동 검증 (`validation.py`)

```
List[Wave] + PatternType
    │
    └── WaveValidator.validate():
            IMPULSE → _validate_impulse():
                - 규칙 1: W2는 W1 시작점 아래로 내려가지 않음
                - 규칙 2: W3는 W1, W5 중 가장 짧지 않음
                - 규칙 3: W4는 W1 고점과 겹치지 않음
                - 가이드라인: W2 되돌림 38.2~78.6% (위반 시 -10%)
                - 가이드라인: W3가 최장 아닐 시 -5%
                - 가이드라인: W3 모멘텀 < W1 시 -10%
            
            ZIGZAG → _validate_zigzag()
            FLAT variants → _validate_flat()
            
            반환: ValidationResult(is_valid, violations, warnings, confidence)
```

### Step 5: 목표가 계산 (`targets.py`)

```
validated waves + pattern
    │
    └── TargetCalculator:
            calculate_retracement(start, end):
                fib_236, fib_382, fib_500, fib_618, fib_786
            
            calculate_extension(start, end, base):
                ext_100, ext_1272, ext_1618, ext_200, ext_2618
            
            calculate_targets(waves, pattern):
                패턴별 주요 레벨 자동 계산
```

### Step 6: WaveAnalysis 조립 (`core.py`)

```python
WaveAnalysis(
    symbol="BTC",
    timeframe="1D",
    pivots=[...],
    waves=[...],
    pattern=PatternType.IMPULSE,
    pattern_confidence=0.78,
    current_position="Wave 4",
    targets={"W5_1618": TargetLevel(price=115000, ...)},
    invalidation_level=85420.0,
    validation=ValidationResult(...)
)
```

### Step 7: 시나리오 생성 (`wave_scenarios.py`)

```
WaveAnalysis
    │
    └── ScenarioGenerator.generate_from_analysis(waves, current_price, symbol):
            _calculate_dynamic_probability(current_price):
                현재가 위치 기반 ABC 조정 / 새 파동 확률 계산
            
            _detect_abc_position(waves):
                A, B, C 파동 완성도 추적
            
            시나리오 생성:
                _create_abc_scenario() → ABC 조정 시나리오
                _create_extended_5th_scenario() → 5파 연장 시나리오
                _create_new_supercycle_scenario() → 새 슈퍼사이클 시나리오
                _create_wave_5_scenario() → W5 진행 중 시나리오
```

### Step 8: 무효화 래핑 (`wave_scenarios.py`)

```
List[WaveScenarioLive]
    │
    └── generate_dynamic_scenarios():
            각 시나리오에 ScenarioWithInvalidation 래핑:
            
            약세/조정 시나리오:
                invalidation_price = recent_high × 1.02
                invalidation_direction = "above"
                valid_until = now + 90일
                
            강세/충격 시나리오:
                invalidation_price = recent_low × 0.98
                invalidation_direction = "below"
                valid_until = now + 120일
                
            횡보/플랫 시나리오:
                invalidation_price = wave_a_start × 1.03
                invalidation_direction = "above"
                valid_until = now + 90일
```

### Step 9: 매매 신호 생성 (`strategy_executor.py`)

```
List[ScenarioWithInvalidation]
    │
    └── StrategyExecutor.generate_signals(scenarios, current_price):
            가격 레벨 수집 (각 레벨에 부모 시나리오 probability 태깅)
            클러스터 강도 계산:
                strength = min(1.0, prob_sum × 0.5 + type_count × 0.15)
            
            신호 생성:
                entry: 클러스터 강도 최상위 레벨
                stop_loss: invalidation_price
                target: 피보나치 확장 레벨
```

---

## 3. 패턴 인식 파이프라인 | Pattern Recognition Pipeline

`PatternRecognizer.recognize(pivots)` 내부 흐름:

```python
checkers = [
    self._check_impulse,           # 6 pivots, 0.65~0.90
    self._check_leading_diagonal,  # 6 pivots, 0.55~0.75
    self._check_ending_diagonal,   # 6 pivots, 0.60~0.80
    self._check_zigzag,            # 4 pivots, 0.60~0.85
    self._check_double_zigzag,     # 8 pivots, 0.50~0.70
    self._check_triple_zigzag,     # 12 pivots, 0.40~0.60
    self._check_flat,              # 4 pivots, 0.60~0.80
    self._check_expanded_flat,     # 4 pivots, 0.55~0.75
    self._check_running_flat,      # 4 pivots, 0.50~0.65
    self._check_triangle,          # 6 pivots, 0.55~0.75
    self._check_complex,           # 8 pivots, 0.40~0.60
]

results = []
for checker in checkers:
    match = checker(pivots)
    if match:
        results.append(match)

if results:
    return max(results, key=lambda m: m.confidence)
else:
    return self._check_unknown(pivots)  # 0.20 기본 신뢰도
```

### 공유 피보나치 헬퍼

모든 체커가 공유하는 4개 헬퍼:

```python
_retrace_ratio(wave_a, wave_b)  → float
    # 되돌림 비율: abs(B) / abs(A)

_in_fib_range(ratio, fib_level, tolerance=0.05)  → bool
    # 피보나치 레벨 ±5% 범위 내 여부

_waves_overlap(wave1_start, wave1_end, wave2_start, wave2_end)  → bool
    # 두 파동의 가격 범위 겹침 여부

_progressive_narrowing(pivots)  → bool
    # 삼각형/대각선 패턴용: 점진적 수렴 여부
```

---

## 4. 시나리오 생성 + 무효화 생애주기 | Scenario Lifecycle

```
생성 (Generation)
    ScenarioGenerator.generate_from_analysis()
        → List[WaveScenarioLive]
        
래핑 (Wrapping)
    generate_dynamic_scenarios()
        → List[ScenarioWithInvalidation]
        각 시나리오: invalidation_price, direction, valid_until, falsifiable_condition
        
실시간 모니터링 (Live Monitoring)
    WaveTracker.update(new_candle)
        → for scenario in scenarios:
               if scenario.is_invalidated(current_price):
                   eliminate → 다음 시나리오로
               if scenario.is_expired():
                   flag → 재평가 요청
                   
소급 조정 (Retroactive Adjustment)
    RetroactiveAdjuster.adjust(tracker, conflict)
        → 과거 파동 레이블 재해석
        → 새 시나리오 세트 생성
```

---

## 5. LLM 계층 | LLM Layer

### 사용 시점

| 모듈 | LLM 사용 조건 | 목적 |
|------|--------------|------|
| `llm_validator.py` | 항상 (선택적) | 알고리즘 신뢰도 보정 |
| `dual_agent_expert.py` | 명시적 호출 시 | Bull/Bear 시나리오 논쟁 |
| `hybrid_expert.py` | `llm_confidence > threshold` 시 | 최종 합성 |
| `rag_expert.py` | 유사 패턴 검색 시 | 역사적 맥락 제공 |

### 토큰 추적

```python
class LLMUsageTracker:
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0
    
    def record(self, response):
        self.total_tokens += response.usage.total_tokens
        self.estimated_cost = self.total_tokens * COST_PER_TOKEN
```

### JSON 파싱 전략 (`llm_utils.safe_parse_json`)

LLM 응답이 항상 유효한 JSON이 아니므로 3단계 폴백:

1. Markdown 코드블록 추출 (````json ... `````)
2. 직접 `json.loads()` 시도
3. 기본 수리 (후행 쉼표, 단따옴표 → 쌍따옴표) 후 재시도

### 클라이언트 싱글턴

```python
# llm_utils.py
_shared_client: Optional[AzureOpenAI] = None

def get_shared_azure_client():
    global _shared_client
    if _shared_client is None:
        _shared_client = get_azure_openai_client()
    return _shared_client
```

리팩토링 전에는 `dual_agent_expert.py`의 각 메서드가 별도로 `AzureOpenAI(...)` 인스턴스를 생성했다. 이제는 모듈 당 하나의 공유 클라이언트를 재사용한다.

---

## 6. 멀티 타임프레임 | Multi-Timeframe Alignment

`multi_timeframe_validator.py`가 담당하는 정렬 검증:

```
일봉 (1D) 분석 결과
    │
    ├── 주봉 (1W) 분석 결과
    │       방향 일치 여부: 같은 방향이면 신뢰도 가중치 증가
    │
    └── 월봉 (1M) 분석 결과
            더 높은 차수의 파동 위치로 현재 위치 확인
            
정렬 점수 계산:
    w3_move = 0 (초기화 보장)  # NameError 수정 사항
    if wave3_detected:
        w3_move = wave3_size
    if w3_move != 0:            # 0 나누기 방지
        alignment_ratio = lower_tf_move / w3_move
```

**정렬 기준:**
- 3개 타임프레임 방향 일치 → 고신뢰 신호
- 2개 일치 → 중간 신호, 주의 필요
- 1개 이하 일치 → 저신뢰, 진입 보류 권장

---

## 7. 설계 결정 기록 (ADR) | Architectural Decision Records

### ADR-001: wave_tracker.py God Object 분해

**결정:** 1,936줄의 `wave_tracker.py`를 3개 모듈로 분리

**이유:**
- 단일 파일이 시나리오 생성, 시각화, 추적 로직을 모두 포함 → 테스트 불가, 수정 위험
- 각 관심사를 분리하면 독립 테스트 및 독립 교체 가능

**결과:**
- `wave_scenarios.py` (757줄): 순수 시나리오 로직, LLM 없음
- `wave_visualization.py` (631줄): 순수 시각화 로직
- `wave_tracker.py` (643줄): 코어 추적 + 위임 메서드만
- 하위 호환성: `wave_tracker`에서 re-export 유지

**트레이드오프:** `wave_tracker.py`가 여전히 `live_tracker.py`에 강한 의존성을 가짐. 추후 `live_tracker.py`도 코어 인터페이스로 추상화 가능.

---

### ADR-002: 시나리오 무효화 방식

**결정:** `ScenarioWithInvalidation` 데이터클래스로 모든 시나리오를 래핑

**이유:**
- 시나리오가 언제 틀렸는지 명확한 기준 없이는 확증 편향에 취약
- 가격 기반 + 시간 기반 두 가지 무효화 기준 필요

**결과:**
- 모든 시나리오에 `invalidation_price`, `invalidation_direction`, `valid_until`, `falsifiable_condition` 내장
- `is_invalidated(price)` / `is_expired()` 메서드로 실시간 체크

**트레이드오프:** 무효화 가격을 `recent_high × 1.02`로 고정. 변동성에 따라 동적 조정이 더 정확하지만, 단순성 우선.

---

### ADR-003: LLM 클라이언트 싱글턴

**결정:** `llm_utils.get_shared_azure_client()`로 모듈 수준 공유 클라이언트 사용

**이유:**
- 리팩토링 전: `dual_agent_expert.py` 내 `validate_scenario()`와 `correct_scenario()`가 각각 별도 `AzureOpenAI(...)` 인스턴스 생성
- HTTP 연결 재사용, 메모리 절약, 테스트 시 모킹 용이

**결과:**
- `llm_utils.py`에 `get_azure_openai_client()` (팩토리) + `get_shared_azure_client()` (싱글턴) 두 함수 제공
- 다른 모듈은 `from llm_utils import get_shared_azure_client` 만으로 클라이언트 획득

---

### ADR-004: 파동 레이블 1-인덱스화

**결정:** 충격파 레이블을 `"0","1","2","3","4","5"` → `"1","2","3","4","5"`로 변경

**이유:**
- 엘리엇 파동 이론 표준 표기법은 1-인덱스 (`Wave 1` ~ `Wave 5`)
- 0-인덱스는 구현 편의를 위한 것으로, 도메인 표준과 충돌

**결과:** 차트, 보고서, 테스트 모두 표준 레이블 사용

---

### ADR-005: 피보나치 기반 사이클 감지

**결정:** `auto_detect_cycle()`에서 균등 분할 → 피보나치 비율 분할

**이유:**
- 엘리엇 파동에서 W3는 시간적으로도 가장 긴 파동
- 균등 분할은 W3 구간을 과소 배분

**결과:** 비율 `1 : 0.618 : 1.618 : 0.618 : 1` (합계 4.854)로 W3에 최대 시간 배분

---

### ADR-006: 신뢰도 페널티 점진적 적용

**결정:** 바이너리 유효/무효 → 위반 심각도별 점진적 페널티

**이유:**
- 엘리엇 파동 규칙은 절대 규칙과 가이드라인으로 구분
- 가이드라인 위반이 즉시 무효를 의미하지 않음

**결과:**
- 절대 규칙 위반 → `is_valid=False`
- 가이드라인 위반 → 신뢰도에서 차감 (-5% ~ -10%)
- 위반 유형과 차감 금액 경고 메시지에 명시
