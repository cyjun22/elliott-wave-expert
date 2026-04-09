# 🌊 Elliott Wave Expert

> 엘리엇 파동 이론 기반 시장 시나리오 분석 엔진
> Elliott Wave Theory-based Market Scenario Analysis Engine

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-98%20passed-green.svg)]()
[![Patterns](https://img.shields.io/badge/patterns-12%2F12-green.svg)]()

---

## 핵심 철학 | Core Philosophy

> **"Elliott Wave는 예측 도구가 아니라 시나리오 맵핑 도구다"**

이 시스템은 시장이 어디로 갈지 '정답'을 맞추려 하지 않는다. 대신:

- **복수 시나리오를 확률 가중치와 함께 제시한다** — ABC 조정, 5파 연장, 새 슈퍼사이클 등 가능한 해석 모두를 병렬로 추적
- **각 시나리오에는 무효화 레벨이 있다** — `ScenarioWithInvalidation`은 가격 기반 무효화 조건과 시간 만료일을 함께 담는다
- **`falsifiable_condition`이 핵심이다** — "BTC가 $95,000을 상향 돌파하면 이 조정 시나리오는 무효" 처럼 명확하게 기술된 반증 조건이 있어야 시나리오가 의미를 갖는다
- **틀린 걸 빨리 아는 것이 목표다** — 맞추는 것보다 빠른 오류 감지가 실전 트레이딩에서 더 가치 있다

---

## 아키텍처 개요 | Architecture Overview

```
OHLCV Data
    │
    ▼
core.py ──── 방향 감지 (SMA slope) / 사이클 감지 (Fibonacci 분할) / 피벗 감지
    │
    ▼
patterns.py ─ 12 패턴 인식 (Impulse, Diagonal, Zigzag, Flat, Triangle, Complex...)
    │
    ▼
validation.py ─ 파동 규칙 검증 + 신뢰도 보정 (위반 시 -5% ~ -10% 페널티)
    │
    ▼
targets.py ── 피보나치 기반 목표가 계산 (되돌림 / 확장 / 프로젝션)
    │
    ▼
wave_scenarios.py ── 시나리오 생성 (ScenarioGenerator) + 무효화 래퍼 (ScenarioWithInvalidation)
    │
    ├──▶ strategy_executor.py ── 매매 신호 (진입 / 손절 / 목표가)
    │
    └──▶ wave_visualization.py ── 차트 (시나리오 경로 / 멀티 타임프레임 / 사분면)
```

**LLM 강화 레이어:**
```
wave_scenarios.py
    │
    ├──▶ dual_agent_expert.py ── Bull vs Bear LLM 토론
    ├──▶ hybrid_expert.py ──── 알고리즘 + LLM 혼합
    └──▶ rag_expert.py ─────── RAG (20개 역사적 패턴 DB 참조)
```

---

## 지원 패턴 | Supported Patterns (12/12)

| 분류 | 패턴 | 영문명 | 최소 피벗 | 신뢰도 범위 | 상태 |
|------|------|--------|-----------|-------------|------|
| 충격파 | 충격파 | Impulse | 6 | 0.65 ~ 0.90 | ✅ |
| 충격파 | 선행 대각선 | Leading Diagonal | 6 | 0.55 ~ 0.75 | ✅ |
| 충격파 | 종결 대각선 | Ending Diagonal | 6 | 0.60 ~ 0.80 | ✅ |
| 조정파 | 지그재그 | Zigzag (ABC) | 4 | 0.60 ~ 0.85 | ✅ |
| 조정파 | 이중 지그재그 | Double Zigzag (WXY) | 8 | 0.50 ~ 0.70 | ✅ |
| 조정파 | 삼중 지그재그 | Triple Zigzag (WXYXZ) | 12 | 0.40 ~ 0.60 | ✅ |
| 조정파 | 플랫 | Flat (Regular) | 4 | 0.60 ~ 0.80 | ✅ |
| 조정파 | 확장형 플랫 | Expanded Flat | 4 | 0.55 ~ 0.75 | ✅ |
| 조정파 | 러닝 플랫 | Running Flat | 4 | 0.50 ~ 0.65 | ✅ |
| 조정파 | 삼각형 | Triangle (ABCDE) | 6 | 0.55 ~ 0.75 | ✅ |
| 조정파 | 복합 조정 | Complex (WXY/WXYXZ) | 8 | 0.40 ~ 0.60 | ✅ |
| 미확정 | 미확정 | Unknown (catch-all) | 1 | 0.20 | ✅ |

---

## 빠른 시작 | Quick Start

### 설치

```bash
pip install pandas numpy matplotlib openai
```

### 기본 분석

```python
import pandas as pd
from elliott_wave.core import ElliottWaveAnalyzer

# OHLCV 데이터 준비
df = pd.read_csv("btc_daily.csv", index_col="date", parse_dates=True)

# 분석기 초기화
analyzer = ElliottWaveAnalyzer()
analysis = analyzer.analyze(df, symbol="BTC", timeframe="1D")

# 결과 출력
print(analysis.summary())
# === BTC (1D) Wave Analysis ===
# Pattern: impulse (78%)
# Current: Wave 4 correction in progress
# Invalidation: $85,420
# Targets:
#   Wave 5 Target (1.618): $115,000
```

### 시나리오 생성 + 무효화 확인

```python
from elliott_wave.wave_scenarios import ScenarioGenerator

generator = ScenarioGenerator()
scenarios = generator.generate_from_analysis(
    waves=analysis.waves,
    current_price=95000,
    symbol="BTC"
)

# 무효화 확인
for s in scenarios:
    print(f"[{s.scenario['name']}]")
    print(f"  무효화 조건: {s.falsifiable_condition}")
    print(f"  만료일: {s.valid_until.date()}")
    print(f"  현재 무효화 여부: {s.is_invalidated(95000)}")
    print(f"  만료 여부: {s.is_expired()}")
```

### 하이브리드 분석 (알고리즘 + LLM)

```python
from elliott_wave.hybrid_expert import HybridElliottExpert

expert = HybridElliottExpert()
result = expert.analyze(df, symbol="BTC", timeframe="1D")

print(f"LLM 보정 신뢰도: {result.llm_confidence:.1%}")
print(f"최종 시나리오: {result.primary_scenario}")
```

### 봉차트 파동 카운트

캔들스틱 차트 위에 파동 번호를 시각적으로 표시한다. 매번 동일한 포맷.

```python
from wave_chart import WaveChart

chart = WaveChart()

# 수동 파동 포인트 지정
chart.plot_manual(df, waves=[
    {"label": "0", "date": "2022-11-21", "price": 15599, "type": "low"},
    {"label": "1", "date": "2023-07-13", "price": 31815, "type": "high"},
    {"label": "2", "date": "2023-09-11", "price": 24797, "type": "low"},
    {"label": "3", "date": "2024-03-14", "price": 73750, "type": "high"},
    {"label": "4", "date": "2024-08-05", "price": 49121, "type": "low"},
    {"label": "5", "date": "2025-01-20", "price": 109115, "type": "high"},
], symbol="BTC-USD", save_path="btc_waves.png")

# core.py 분석 결과에서 자동 추출
chart.plot(df, analysis=analysis, save_path="auto_waves.png")
```

```bash
# CLI 데모
python wave_chart.py --sample
python wave_chart.py --csv data.csv --symbol ETH-USD -o eth_waves.png
```

표시 항목:
- 캔들스틱 (다크 테마, 상승 초록 / 하락 빨간)
- 파동 번호 원형 배지 (파동별 고유 색상)
- 파동 간 지그재그 연결선
- 각 피봇 가격 태그
- 거래량 서브플롯
- 무효화 레벨 수평선 (선택)
- 목표가 영역 (선택)

### 시나리오 경로 차트

```python
from elliott_wave.wave_visualization import WaveVisualizer

visualizer = WaveVisualizer(tracker)
fig = visualizer.get_scenario_chart(symbol="BTC", timeframe="1D")
fig.savefig("btc_wave_analysis.png", dpi=150, bbox_inches="tight")
```

### 시각적 보고서 생성

매 실행마다 동일한 포맷의 HTML 분석 보고서를 생성한다.

```bash
# CLI로 보고서 생성
python report_generator.py                     # → reports/elliott_report_YYYYMMDD_HHMMSS.html
python report_generator.py -o analysis.html    # 지정 경로
python report_generator.py --json              # JSON 데이터만
```

```python
# Python API
from report_generator import ReportGenerator

gen = ReportGenerator(project_root=".")
gen.generate("output/report.html")
gen.generate_json("output/report.json")
```

보고서에 포함되는 항목:
- **Quality Score** — 독스트링 커버리지, 테스트 통과율, 패턴 구현율, 보안 이슈 기반 종합 점수 (0-100)
- **KPI 대시보드** — 파일 수, 총 라인, 클래스/함수 수, 패턴 구현 현황, 테스트 통과율
- **Pattern Implementation** — 12종 패턴별 구현 상태 + 테스트 커버리지
- **Module Architecture** — 6개 모듈 그룹 시각화 (Core, Tracking, AI, Multi-agent, Visualization, Execution)
- **File Metrics** — 파일별 라인 수, 클래스/함수 수, 사이즈 바, 독스트링 비율
- **Git History** — 커밋별 변경 통계 (+/- 라인)
- **Security Scan** — bare except, SQL injection, eval/exec 탐지

---

## 시나리오 무효화 시스템 | Scenario Invalidation System

`ScenarioWithInvalidation`은 모든 시나리오에 반증 가능성을 부여한다.

```python
from elliott_wave.wave_scenarios import ScenarioWithInvalidation
from datetime import datetime, timedelta

scenario = ScenarioWithInvalidation(
    scenario={"name": "ABC Correction", "probability": 0.45},
    invalidation_price=95_200,          # 이 가격 돌파 시 무효
    invalidation_direction="above",     # 위로 돌파 시
    valid_until=datetime.now() + timedelta(days=90),
    falsifiable_condition=(
        "BTC가 $95,200 (최근 고점 × 1.02)을 상향 돌파하면 "
        "ABC 조정 시나리오는 무효화되며, 5파 연장 또는 새 사이클 시작을 검토해야 한다."
    )
)

# 실시간 체크
current_price = 96_000
if scenario.is_invalidated(current_price):
    print("⚠️ 시나리오 무효화: 다음 시나리오로 전환")

if scenario.is_expired():
    print("⏰ 유효 기간 만료: 시나리오 재평가 필요")
```

**무효화 가격 계산 기준:**

| 시나리오 유형 | 무효화 방향 | 기준 | 유효 기간 |
|--------------|------------|------|----------|
| 약세 / 조정 | 위로 돌파 | 최근 고점 × 1.02 | 90일 |
| 강세 / 충격파 | 아래로 돌파 | 최근 저점 × 0.98 | 120일 |
| 횡보 / 플랫 | 위로 돌파 | A파 시작점 × 1.03 | 90일 |

---

## LLM 통합 | LLM Integration

LLM은 알고리즘 분석을 **보완**하지 **대체**하지 않는다.

### 구조

```
llm_utils.py ──── 공유 클라이언트 싱글턴 + JSON 파싱 유틸리티
    │
    ├── dual_agent_expert.py ── Bull LLM vs Bear LLM 독립 분석 후 합성
    ├── llm_validator.py ────── 알고리즘 결과 LLM 검증 + 신뢰도 조정
    └── rag_expert.py ──────── 20개 역사적 패턴 DB 기반 유사 사례 검색
```

### 사용 흐름

1. 알고리즘이 패턴/시나리오 초안 생성
2. LLM이 해석 타당성 검토 및 신뢰도 보정
3. RAG가 유사 역사적 사례 조회 (예: "BTC 2019 Leading Diagonal → 새 슈퍼사이클")
4. 최종 결과: 알고리즘 신뢰도 + LLM 조정 계수

### 환경 변수 설정

```bash
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your-api-key"
```

### 토큰 추적

```python
from elliott_wave.llm_validator import LLMWaveValidator

validator = LLMWaveValidator()
result = validator.validate(waves, pattern)

print(f"사용 토큰: {validator.usage_tracker.total_tokens}")
print(f"예상 비용: ${validator.usage_tracker.estimated_cost:.4f}")
```

---

## 테스트 | Testing

```bash
# 전체 테스트 실행
pytest tests/ -v

# 특정 테스트 파일
pytest tests/test_patterns.py -v    # 12 패턴 (20개 테스트)
pytest tests/test_core.py -v        # 분석기 코어 (17개 테스트)
pytest tests/test_scenarios.py -v   # 시나리오 시스템 (14개 테스트)
pytest tests/test_validation.py -v  # 파동 규칙 검증 (19개 테스트)
```

**테스트 커버리지: 70개 테스트 100% 통과**

| 파일 | 테스트 수 | 검증 항목 |
|------|----------|----------|
| `test_patterns.py` | 20 | 12 패턴 타입 인식, 피보나치 비율, 신뢰도 범위 |
| `test_core.py` | 17 | 방향 감지, 사이클 감지, 피벗 감지, 입력 검증 |
| `test_scenarios.py` | 14 | 무효화 체크, 만료 체크, 시나리오 생성기 |
| `test_validation.py` | 19 | 규칙 위반, 신뢰도 페널티, 무효화 레벨 계산 |

---

## 프로젝트 구조 | Project Structure

```
elliott-wave-expert/
│
├── core.py                     # 핵심 분석기 (방향/사이클/피벗 감지, WaveAnalysis)
├── patterns.py                 # 12 패턴 정의 및 인식 (PatternType, PatternRecognizer)
├── validation.py               # 파동 규칙 검증 + 신뢰도 페널티 (WaveValidator)
├── targets.py                  # 피보나치 목표가 계산 (TargetCalculator)
│
├── wave_scenarios.py           # 시나리오 생성 + 무효화 래퍼 (ScenarioGenerator, ScenarioWithInvalidation)
├── wave_visualization.py       # 차트 생성 (WaveVisualizer: 시나리오/멀티TF/사분면)
├── wave_tracker.py             # 통합 추적기, 643줄 (wave_scenarios + wave_visualization 위임)
├── wave_path_generator.py      # 미래 가격 경로 시뮬레이션
│
├── scenario_tree.py            # 베이지안 시나리오 확률 트리 (ProbabilityEngine)
├── scenario_chart.py           # 시나리오 시각화 (경로 차트)
├── adaptive_tracker.py         # ATH 인식 적응형 추적 (ScenarioType 상수)
│
├── dual_agent_expert.py        # Bull vs Bear LLM 이중 에이전트
├── hybrid_expert.py            # 알고리즘 + LLM 혼합 전문가
├── multi_agent_system.py       # 멀티 에이전트 오케스트레이션
├── rag_expert.py               # RAG 강화 전문가
├── pattern_rag.py              # 역사적 패턴 DB (20개: BTC/ETH/SPX/GOLD/TSLA 등)
│
├── llm_utils.py                # LLM 공유 유틸리티 (싱글턴 클라이언트, JSON 파싱)
├── llm_validator.py            # LLM 기반 파동 검증 + 토큰 추적
│
├── strategy_executor.py        # 매매 신호 생성 (진입/손절/목표가)
├── multi_timeframe_validator.py # 멀티 타임프레임 정렬 검증
├── subwave_analyzer.py         # 서브파동 분해 분석
├── retroactive_adjuster.py     # 소급 파동 조정
│
├── data_validator.py           # OHLCV 입력 데이터 검증
├── tracker_history.py          # SQLite 추적 이력 (parameterized queries)
├── chart_renderer.py           # 차트 렌더링 유틸리티
├── ai_strategist_report.py     # AI 전략 보고서 생성
│
├── __init__.py                 # 패키지 초기화 (graceful import)
├── CHANGELOG.md                # 변경 이력
│
├── tests/
│   ├── conftest.py             # 공유 픽스처 (Pivot/Wave/OHLCV 팩토리)
│   ├── test_patterns.py        # 패턴 인식 테스트 (20개)
│   ├── test_core.py            # 코어 분석기 테스트 (17개)
│   ├── test_scenarios.py       # 시나리오 시스템 테스트 (14개)
│   └── test_validation.py      # 검증 규칙 테스트 (19개)
│
└── docs/
    ├── ARCHITECTURE.md         # 상세 아키텍처 문서
    └── REFACTORING_REPORT.md   # 리팩토링 보고서
```

---

## 기여 | Contributing

### 새 패턴 추가하기

1. `patterns.py`의 `PatternType` enum에 새 항목 추가
2. `PatternRecognizer`에 `_check_<pattern_name>()` 메서드 구현
3. `recognize()` 메서드 내 체커 목록에 추가
4. `get_pattern_description()` 업데이트
5. `tests/test_patterns.py`에 테스트 추가

```python
# patterns.py 예시
def _check_my_new_pattern(self, pivots: List[Pivot]) -> Optional[PatternMatch]:
    if len(pivots) < 6:
        return None
    # ... 피보나치 비율 검증 로직
    confidence = self._calculate_confidence(pivots)
    return PatternMatch(
        pattern=PatternType.MY_NEW_PATTERN,
        confidence=confidence,
        pivots=pivots
    )
```

### 새 전문가 에이전트 추가하기

`HybridElliottExpert`를 상속하거나 독립 클래스로 구현 후 `multi_agent_system.py`에 등록:

```python
class MyCustomExpert:
    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
        # ...
        return {"scenarios": [...], "confidence": 0.75}
```

### RAG 패턴 DB 확장

`pattern_rag.py`의 `HISTORICAL_PATTERNS` 딕셔너리에 항목 추가:

```python
"my_2024_pattern": {
    "symbol": "BTC",
    "pattern_type": "triangle",
    "outcome": "abc_correction",
    "fib_ratios": {"wave_b": 0.618, "wave_c": 1.272},
    "market_condition": "post-halving consolidation",
    "failure_mode": "triangle_breakdown",
    "notes": "..."
}
```

---

## 라이선스 | License

MIT License — 자유롭게 사용, 수정, 배포 가능.

상업적 사용 시 역사적 패턴 데이터의 출처를 명시해 주세요.
