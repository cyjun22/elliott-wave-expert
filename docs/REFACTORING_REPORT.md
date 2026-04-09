# 리팩토링 보고서 | Refactoring Report

> Elliott Wave Expert v1.x → v2.0 리팩토링 상세 기록
>
> 작성일: 2026-04-08 ~ 2026-04-09
> 작성자: Automated Refactoring Session

---

## 1. 진단 결과 요약 | Diagnosis Summary

코드베이스 초기 진단에서 발견된 주요 문제점:

| 범주 | 문제 | 심각도 |
|------|------|--------|
| 아키텍처 | `wave_tracker.py` God Object (1,936줄) | 높음 |
| 기능 누락 | `patterns.py` 12개 중 3개만 구현 | 높음 |
| 보안 | SQL Injection (`tracker_history.py`) | 높음 |
| 버그 | `NameError` — `w3_move` 미초기화 | 중간 |
| 버그 | DataFrame 변이 (`hybrid_expert.py`) | 중간 |
| 보안 | `tempfile.mktemp()` 레이스 컨디션 | 중간 |
| 코드 품질 | Bare `except:` (`retroactive_adjuster.py`) | 낮음 |
| 관찰성 | Import 실패 silent pass (`__init__.py`) | 낮음 |
| 유지보수성 | LLM 클라이언트 각 메서드별 재생성 | 중간 |
| 테스트 | 테스트 코드 없음 | 높음 |

---

## 2. 변경 파일 요약표 | Changed Files Summary

| 파일 | 변경 유형 | Before | After | 핵심 변경 내용 |
|------|----------|--------|-------|--------------|
| `wave_tracker.py` | 축소 | 1,936줄 | 643줄 | 시나리오/시각화 분리, 위임 패턴 적용 |
| `patterns.py` | 대폭 확장 | 328줄 | 1,071줄 | 3/12 → 12/12 패턴 완전 구현 |
| `pattern_rag.py` | 확장 | 5개 패턴 | 20개 패턴 | 7개 자산군, 10개 패턴 유형 추가 |
| `core.py` | 개선 | - | - | SMA slope 방향 감지, Fibonacci 사이클, 입력 검증 |
| `validation.py` | 개선 | - | - | 점진적 신뢰도 페널티 (-5%/-10%) 도입 |
| `tracker_history.py` | 보안 수정 | - | - | f-string → parameterized queries |
| `multi_timeframe_validator.py` | 버그 수정 | - | - | `w3_move = 0` 초기화, 0 나누기 방지 |
| `hybrid_expert.py` | 버그 수정 | - | - | `df.copy()` 추가 (원본 변이 방지) |
| `chart_renderer.py` | 보안 수정 | - | - | `mktemp()` → `NamedTemporaryFile()` |
| `retroactive_adjuster.py` | 코드 품질 | - | - | `except:` → `except (JSONDecodeError, IOError, OSError):` |
| `dual_agent_expert.py` | 리팩토링 | - | - | 공유 LLM 클라이언트, 공유 JSON 파싱 적용 |
| `scenario_tree.py` | 기능 추가 | - | - | 설정 가능한 확률 멀티플라이어 |
| `adaptive_tracker.py` | 코드 품질 | - | - | `ScenarioType` 상수 클래스 도입 |
| `strategy_executor.py` | 개선 | - | - | 확률 가중 클러스터 강도 계산 |
| `subwave_analyzer.py` | 버그 수정 | - | - | 가격 기반 방향 감지 (레이블 기반 → 실제 가격 비교) |
| `__init__.py` | 관찰성 | - | - | Import 실패 로깅 추가 |

**신규 생성 파일:**

| 파일 | 목적 | 크기 |
|------|------|------|
| `wave_scenarios.py` | 시나리오 생성 엔진 (God Object에서 분리) | 758줄 |
| `wave_visualization.py` | 차트 시각화 (God Object에서 분리) | 631줄 |
| `llm_utils.py` | 공유 LLM 유틸리티 | 101줄 |
| `tests/conftest.py` | 공유 테스트 픽스처 | 180줄 |
| `tests/test_patterns.py` | 패턴 인식 테스트 20개 | 14,062바이트 |
| `tests/test_core.py` | 코어 분석기 테스트 17개 | 8,785바이트 |
| `tests/test_scenarios.py` | 시나리오 시스템 테스트 14개 | 6,574바이트 |
| `tests/test_validation.py` | 검증 규칙 테스트 19개 | 11,500바이트 |

---

## 3. 패턴별 구현 상세 | Pattern Implementation Details

### 기존 구현 (v1.x)

v1.x에서 구현되어 있던 3개 패턴:
- `IMPULSE` — 기본 5파 충격파
- `ZIGZAG` — ABC 지그재그
- `FLAT` — 레귤러 플랫

### 신규 구현 (v2.0) — 9개 패턴

---

#### 3-1. 선행 대각선 | Leading Diagonal

- **패턴 이름 (한글/영어):** 선행 대각선 / Leading Diagonal
- **출현 위치:** W1 또는 A파 위치 — 새 충격파의 첫 번째 파동으로 나타남
- **인식 규칙 요약:**
  - 최소 6개 피벗 필요
  - 각 서브파동이 5파 구조(또는 3파) 형성
  - 파동들이 점진적으로 수렴하는 쐐기 모양
  - W4가 W1과 겹침 허용 (일반 충격파와 차이)
- **피보나치 기준:**
  - W2 되돌림: W1의 38.2% ~ 78.6%
  - W3 > W1 (W3 최단 금지)
  - W4 되돌림: W3의 38.2% ~ 78.6%
  - 점진적 수렴: 각 파동이 이전 파동보다 짧아짐
- **신뢰도 범위:** 0.55 ~ 0.75
- **예시 시장 상황:** BTC 2019년 3,500달러 저점 이후 시작된 상승파 초기 단계

---

#### 3-2. 종결 대각선 | Ending Diagonal

- **패턴 이름 (한글/영어):** 종결 대각선 / Ending Diagonal
- **출현 위치:** W5 또는 C파 위치 — 추세의 종결 국면에서 나타남
- **인식 규칙 요약:**
  - 최소 6개 피벗 필요
  - 모든 서브파동이 3파 구조
  - 명확한 쐐기 모양 (상승 추세: 하향 수렴, 하락 추세: 상향 수렴)
  - W4가 W1 가격 범위와 반드시 겹침
- **피보나치 기준:**
  - W3 < W1 (선행 대각선과 반대)
  - W5 < W3
  - W4 > W2 (각 되돌림이 이전보다 깊어짐)
- **신뢰도 범위:** 0.60 ~ 0.80
- **예시 시장 상황:** SPX 2018년 말 상승 추세 최종 국면, 이후 급락 연결

---

#### 3-3. 이중 지그재그 | Double Zigzag (WXY)

- **패턴 이름 (한글/영어):** 이중 지그재그 / Double Zigzag
- **출현 위치:** 복합 조정 2파 또는 4파 — 두 번의 지그재그가 X파로 연결
- **인식 규칙 요약:**
  - 최소 8개 피벗 필요
  - W-X-Y 구조: 각각의 W와 Y가 독립적인 ABC 지그재그
  - X파는 선행 W파의 38.2% ~ 78.6% 되돌림
- **피보나치 기준:**
  - W 지그재그: B < 61.8% 되돌림, C = A의 100% ~ 161.8%
  - X파 되돌림: 38.2% ~ 78.6%
  - Y 지그재그: W와 유사한 구조 반복
- **신뢰도 범위:** 0.50 ~ 0.70
- **예시 시장 상황:** ETH 2022년 2~6월 하락 조정 — 두 차례 ABC 패턴이 연속 출현

---

#### 3-4. 삼중 지그재그 | Triple Zigzag (WXYXZ)

- **패턴 이름 (한글/영어):** 삼중 지그재그 / Triple Zigzag
- **출현 위치:** 장기 횡보 조정의 끝단 — 매우 드문 패턴
- **인식 규칙 요약:**
  - 최소 12개 피벗 필요
  - W-X-Y-X-Z 구조: 세 개의 지그재그가 두 X파로 연결
  - 각 X파는 선행 지그재그의 50% ~ 90% 복귀
- **피보나치 기준:** 이중 지그재그와 동일한 내부 규칙, X파가 두 개
- **신뢰도 범위:** 0.40 ~ 0.60 (패턴이 복잡할수록 신뢰도 하락)
- **예시 시장 상황:** DJIA 1966~1974년 장기 횡보 — 역사적으로 기록된 삼중 지그재그

---

#### 3-5. 확장형 플랫 | Expanded Flat

- **패턴 이름 (한글/영어):** 확장형 플랫 / Expanded Flat
- **출현 위치:** 2파 또는 4파 — B파가 A 시작점을 초과하는 강한 반등 포함
- **인식 규칙 요약:**
  - 최소 4개 피벗 필요
  - B파가 A파 시작점을 초과 (A 시작점의 105% 이상)
  - C파가 A파 끝점을 초과 (A 끝점의 100% ~ 138.2% 연장)
- **피보나치 기준:**
  - B 되돌림: > 100% (A 시작점 초과)
  - C 연장: A의 100% ~ 161.8%
- **신뢰도 범위:** 0.55 ~ 0.75
- **예시 시장 상황:** SPX 2015년 8월 급락 전 — B파가 직전 고점을 소폭 갱신 후 급락

---

#### 3-6. 러닝 플랫 | Running Flat

- **패턴 이름 (한글/영어):** 러닝 플랫 / Running Flat
- **출현 위치:** 강한 4파 조정 — 상승 추세가 강할 때 조정이 얕게 끝남
- **인식 규칙 요약:**
  - 최소 4개 피벗 필요
  - B파가 A 시작점을 초과 (확장형 플랫과 동일)
  - C파가 A파 끝점에 도달하지 못함 (A 끝점의 100% 미만)
  - 이것이 러닝 플랫의 핵심 — C가 짧다는 것은 추세가 강하다는 신호
- **피보나치 기준:**
  - B 되돌림: > 100%
  - C: A의 61.8% ~ 100% 미만
- **신뢰도 범위:** 0.50 ~ 0.65
- **예시 시장 상황:** SPX 2014년 Bull Market 중 4파 조정 — 이후 5파 연장으로 연결

---

#### 3-7. 삼각형 | Triangle (ABCDE)

- **패턴 이름 (한글/영어):** 삼각형 / Triangle
- **출현 위치:** 4파 또는 B파 — 돌파 전 에너지 압축 국면
- **인식 규칙 요약:**
  - 최소 6개 피벗 (A, B, C, D, E) 필요
  - 각 파동 A > B > C > D > E (점진적 수렴)
  - A-C 추세선과 B-D 추세선이 수렴
  - 돌파 방향이 전체 추세 방향과 일치
- **피보나치 기준:**
  - B 되돌림: A의 38.2% ~ 78.6%
  - C: B의 38.2% ~ 78.6% 되돌림
  - D: C의 38.2% ~ 78.6%
  - E: D의 38.2% ~ 78.6% (가장 짧은 파동)
- **신뢰도 범위:** 0.55 ~ 0.75
- **예시 시장 상황:** BTC 2019년 6~9월 삼각형 — 이후 하방 돌파로 반례 사례로도 유명

---

#### 3-8. 복합 조정 | Complex (WXY/WXYXZ)

- **패턴 이름 (한글/영어):** 복합 조정 / Complex Correction
- **출현 위치:** 장기 2파 또는 4파 — 여러 조정 패턴이 X파로 연결된 복합체
- **인식 규칙 요약:**
  - 최소 8개 피벗 필요
  - W: Zigzag, Flat, Triangle 중 하나
  - X: 연결 파동 (W의 38.2% ~ 78.6% 되돌림)
  - Y: 또 다른 조정 패턴 (W와 동일하거나 다른 유형 가능)
- **피보나치 기준:** 내부 W, Y 패턴의 각 피보나치 규칙 준수 + X 되돌림
- **신뢰도 범위:** 0.40 ~ 0.60
- **예시 시장 상황:** SPX 2000~2003년 닷컴 버블 붕괴 — Zigzag + Flat의 복합 구조

---

#### 3-9. 미확정 | Unknown (Catch-All)

- **패턴 이름 (한글/영어):** 미확정 / Unknown
- **출현 위치:** 어떤 위치에서도 — 다른 11개 패턴이 모두 불일치할 때 반환
- **인식 규칙 요약:**
  - 피벗이 1개 이상 있으면 반환
  - 시스템이 분석을 멈추지 않도록 하는 폴백
- **신뢰도:** 고정 0.20
- **용도:** 데이터가 불충분하거나 비표준 패턴일 때, 다음 시나리오 재평가 플래그

---

## 4. 시나리오 무효화 시스템 설계 상세 | Scenario Invalidation System Design

### 4-1. ScenarioWithInvalidation 구조

```python
@dataclass
class ScenarioWithInvalidation:
    scenario: Dict                 # 원본 시나리오 딕셔너리
    invalidation_price: float      # 무효화 트리거 가격
    invalidation_direction: str    # 'above' | 'below'
    valid_until: datetime          # 시간 기반 만료
    falsifiable_condition: str     # 사람이 읽을 수 있는 조건 설명

    def is_invalidated(self, current_price: float) -> bool:
        if self.invalidation_direction == 'above':
            return current_price > self.invalidation_price
        elif self.invalidation_direction == 'below':
            return current_price < self.invalidation_price
        return False

    def is_expired(self, now: datetime = None) -> bool:
        if now is None:
            now = datetime.now()
        return now > self.valid_until
```

### 4-2. 무효화 가격 계산 방법

60개 봉(bar) 룩백으로 최근 고/저점 계산:

```python
# 최근 60봉의 고/저점
recent_prices = [bar.close for bar in recent_bars[-60:]]
recent_high = max(recent_prices)
recent_low = min(recent_prices)

# 약세/조정 시나리오
invalidation_price = recent_high * 1.02   # 2% 버퍼
invalidation_direction = "above"

# 강세/충격 시나리오
invalidation_price = recent_low * 0.98    # 2% 버퍼
invalidation_direction = "below"

# 횡보/플랫 시나리오
invalidation_price = wave_a_start_price * 1.03
invalidation_direction = "above"
```

### 4-3. 시간 기반 만료

파동 유형별 유효 기간 설정 근거:

| 시나리오 유형 | 유효 기간 | 근거 |
|--------------|----------|------|
| 약세/조정 | 90일 | ABC 조정은 통상 1~3달 내 완성 |
| 강세/충격 | 120일 | 충격파는 더 긴 전개 기간 필요 |
| 횡보/플랫 | 90일 | 플랫 조정은 ABC 조정과 유사한 기간 |

```python
valid_until = datetime.now() + timedelta(days=90)   # 약세/플랫
valid_until = datetime.now() + timedelta(days=120)  # 강세
```

### 4-4. falsifiable_condition 예시

실제 `ScenarioGenerator`가 생성하는 조건 문자열 예시:

```
# ABC 조정 시나리오
"BTC가 $95,200 (최근 60봉 고점 $93,333 × 1.02)을 상향 돌파하면
 ABC 조정 시나리오는 무효화됩니다. 5파 연장 또는 새 슈퍼사이클 시작을
 우선 시나리오로 전환하세요. 유효 기간: 2026-07-09까지."

# 5파 연장 시나리오
"BTC가 $88,200 (최근 60봉 저점 $90,000 × 0.98)을 하향 이탈하면
 5파 연장 시나리오는 무효화됩니다. ABC 조정 또는 새 하락 사이클을
 우선 시나리오로 전환하세요. 유효 기간: 2026-08-08까지."
```

---

## 5. 보안 수정 상세 | Security Fix Details

### 5-1. SQL Injection — tracker_history.py

**Before (취약):**
```python
query = f"SELECT * FROM wave_history WHERE symbol = '{symbol}'"
conn.execute(query)
```

**After (안전):**
```python
query = "SELECT * FROM wave_history WHERE symbol = ?"
conn.execute(query, (symbol,))

# pd.read_sql_query 사용 시
df = pd.read_sql_query(query, conn, params=(symbol,))
```

`symbol` 파라미터에 `'; DROP TABLE wave_history; --` 같은 값이 들어와도 안전.

---

### 5-2. tempfile 레이스 컨디션 — chart_renderer.py

**Before (취약):**
```python
# mktemp()는 파일 이름만 반환하고 생성하지 않음 → 경쟁 조건 발생 가능
tmp_path = tempfile.mktemp(suffix='.png')
```

**After (안전):**
```python
import tempfile
with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
    tmp_path = f.name
# 파일이 원자적으로 생성됨 → 경쟁 조건 없음
```

---

### 5-3. Bare Except — retroactive_adjuster.py

**Before:**
```python
try:
    data = json.load(f)
except:           # SystemExit, KeyboardInterrupt도 잡힘
    data = {}
```

**After:**
```python
try:
    data = json.load(f)
except (json.JSONDecodeError, IOError, OSError):
    data = {}     # 예상된 오류만 처리
```

---

## 6. 테스트 상세 | Test Details

### 6-1. tests/conftest.py — 공유 픽스처

모든 테스트 파일이 공유하는 팩토리 픽스처:

```python
@pytest.fixture
def make_pivot()    → Pivot 생성기 (가격, 날짜 오프셋, 타입)
@pytest.fixture
def make_wave()     → Wave 생성기 (시작/끝 가격, 날짜, 라벨)
@pytest.fixture
def bullish_impulse_pivots()   → 교과서적 상승 5파 (6개 피벗)
@pytest.fixture
def bearish_impulse_pivots()   → 하락 5파 (6개 피벗)
@pytest.fixture
def zigzag_pivots()            → ABC 지그재그 (4개 피벗)
@pytest.fixture
def flat_pivots()              → 레귤러 플랫 (4개 피벗)
@pytest.fixture
def make_ohlcv_df()            → 합성 OHLCV DataFrame (추세/변동성 설정 가능)
```

### 6-2. test_patterns.py (20개 테스트)

| 테스트 이름 | 검증 내용 |
|------------|----------|
| `test_impulse_basic` | 교과서 충격파 인식 → IMPULSE |
| `test_impulse_bullish_confidence` | 신뢰도 0.65 이상 |
| `test_leading_diagonal` | 쐐기 + W4 겹침 → LEADING_DIAGONAL |
| `test_ending_diagonal` | W3 < W1, W5 < W3 → ENDING_DIAGONAL |
| `test_zigzag_basic` | ABC 구조 → ZIGZAG |
| `test_double_zigzag` | WXY 구조 → DOUBLE_ZIGZAG |
| `test_triple_zigzag` | WXYXZ 구조 → TRIPLE_ZIGZAG |
| `test_flat_regular` | B ≈ A 시작, C ≈ A 끝 → FLAT |
| `test_expanded_flat` | B > A 시작 → EXPANDED_FLAT |
| `test_running_flat` | B > A 시작, C < A 끝 → RUNNING_FLAT |
| `test_triangle` | ABCDE 수렴 → TRIANGLE |
| `test_complex` | WXY 복합 → COMPLEX |
| `test_unknown_fallback` | 불일치 → UNKNOWN (신뢰도 0.20) |
| ... 등 20개 | |

### 6-3. test_core.py (17개 테스트)

- 방향 감지: 상승 추세 / 하락 추세 / 횡보 처리
- 사이클 감지: Fibonacci 비율 적용 확인
- 피벗 감지: 고점/저점 정확도
- 입력 검증: 30개 미만 캔들, NaN, 중복 타임스탬프, 극단 변동

### 6-4. test_scenarios.py (14개 테스트)

- `ScenarioWithInvalidation.is_invalidated()`: above/below 방향
- `ScenarioWithInvalidation.is_expired()`: 만료 여부
- `ScenarioGenerator.generate_from_analysis()`: 시나리오 수, 확률 합
- 무효화 가격이 실제 가격보다 의미 있는 버퍼 가짐 여부

### 6-5. test_validation.py (19개 테스트)

- 절대 규칙 위반 감지 (W2 > W1 시작점, W4 겹침)
- 가이드라인 위반 시 페널티 적용 (-5%, -10%)
- 유효한 충격파의 신뢰도 기준치 이상 유지
- Zigzag / Flat 검증 규칙

---

## 7. 남은 개선 과제 | Remaining Improvements

### 7-1. wave_tracker.py 추가 분해

현재 643줄로 축소되었지만 여전히 `live_tracker.py`에 강한 결합:

```python
# 현재 상태 — 강한 결합
from experts.elliott.live_tracker import (
    WaveScenarioLive, WaveType, WavePosition,
    InvalidationRule, TargetLevel, MarketState, TrackingResult
)
```

**제안:** `live_tracker.py`의 데이터클래스들을 `core.py` 또는 별도 `types.py`로 이동하여 패키지 독립성 강화.

### 7-2. 실시간 데이터 연동

현재 시스템은 배치(Batch) 분석만 지원. 개선 방향:

```python
# 현재 (배치)
analyzer.analyze(historical_df, symbol, timeframe)

# 목표 (스트리밍)
async for candle in live_feed:
    tracker.update(candle)
    signals = tracker.get_live_signals()
```

- WebSocket 기반 실시간 피드 연동 레이어 필요
- `tracker.update()` 이미 구현됨 — 피드 어댑터만 추가하면 됨

### 7-3. Seed Flower 시스템 통합 계획

외부 AI 오케스트레이션 시스템(Seed Flower)과의 통합 로드맵:

| 단계 | 내용 | 예상 기간 |
|------|------|----------|
| 1 | `HybridElliottExpert.analyze()` REST API 래핑 | 1주 |
| 2 | 시나리오를 Seed Flower 이벤트로 발행 | 2주 |
| 3 | Seed Flower → 무효화 이벤트 구독 → `tracker.update()` 콜백 | 3주 |
| 4 | 멀티 심볼 병렬 추적 | 4주 |

### 7-4. 패턴 신뢰도 캘리브레이션

현재 신뢰도 범위가 규칙 기반(rule-based)으로 수동 설정됨. 개선 방향:
- `pattern_rag.py`의 20개 역사적 패턴으로 실제 결과 대비 신뢰도 역산
- 베이지안 업데이트로 실제 예측 정확도 기반 캘리브레이션

### 7-5. 테스트 커버리지 확장

현재 커버되지 않은 영역:
- `dual_agent_expert.py` — LLM mock 필요
- `wave_tracker.py` 통합 테스트 — `live_tracker.py` stub 필요
- `strategy_executor.py` — 신호 생성 end-to-end 테스트
- `multi_timeframe_validator.py` — 복수 타임프레임 정렬 케이스
