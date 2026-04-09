# Elliott Wave Expert

엘리엇 파동 분석 + 시나리오 예측 시스템. Seed Flower 멀티에이전트 트레이딩 OS의 기술적 분석 전문가 모듈.

## 아키텍처

```
OHLCV Data (1d/4h/1h)
        │
        ▼
┌─────────────────────┐
│   ForecastEngine    │ ← 통합 파이프라인
│   run_full_pipeline │
└────────┬────────────┘
         │
    ┌────┴────┬────────────┬──────────────┐
    ▼         ▼            ▼              ▼
┌────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐
│ core.py│ │Scenario  │ │Timeframe   │ │Probability   │
│ 12/12  │ │Generator │ │Linker      │ │Engine        │
│patterns│ │4 scenarios│ │R1-R5 rules │ │Bayesian      │
└────────┘ └──────────┘ └────────────┘ └──────────────┘
                │                              │
                ▼                              ▼
         ┌──────────┐                  ┌──────────────┐
         │Scenario  │                  │Adaptive      │
         │Tree      │                  │Tracker       │
         │manage/   │                  │realtime      │
         │invalidate│                  │reclassify    │
         └────┬─────┘                  └──────┬───────┘
              │                               │
              └───────────┬───────────────────┘
                          ▼
                   ┌─────────────┐
                   │ WaveChart   │
                   │ candlestick │
                   │ + forecast  │
                   │   paths     │
                   └─────────────┘
```

## 핵심 모듈

| 모듈 | 설명 | 줄 수 |
|------|------|-------|
| `forecast_engine.py` | 통합 예측 파이프라인 — 데이터→분석→시나리오→예측→업데이트 | 332 |
| `timeframe_linker.py` | 멀티타임프레임 교차 제약 검증 (R1~R5) | 340 |
| `realtime_loop.py` | 실시간 캔들 업데이트 루프 + 알림 | 250 |
| `wave_chart.py` | 봉차트 + 파동 카운트 + 미래 시나리오 경로 (점선) | 900 |
| `core.py` | 파동 분석 엔진 (피벗 감지, 패턴 매칭) | 750 |
| `patterns.py` | 12/12 엘리엇 패턴 구현 | 1,250 |
| `wave_scenarios.py` | 4개 시나리오 자동 생성 + 동적 확률 | 758 |
| `scenario_tree.py` | 시나리오 트리 관리 + 무효화 + 베이지안 확률 | 327 |
| `adaptive_tracker.py` | 실시간 파동 재분류 (확정/임시/무효화) | 376 |
| `multi_timeframe_validator.py` | 다중 타임프레임 합의 검증 | 430 |

## 사용법

### 전체 파이프라인

```python
from forecast_engine import ForecastEngine

engine = ForecastEngine('BTC-USD')

# 타임프레임별 OHLCV 캔들 데이터
timeframe_data = {
    '1d': daily_candles,   # [{'date':..,'open':..,'high':..,'low':..,'close':..,'volume':..}]
    '4h': h4_candles,
    '1h': h1_candles,
}

# 전체 분석 실행
result = engine.run_full_pipeline(timeframe_data)

print(result.primary_scenario.name)     # "Zigzag ABC (조정)"
print(result.primary_scenario.probability)  # 0.55
print(result.overall_bias)              # "bearish"
print(len(result.forecast_paths))       # 4

# 미래 경로
for path in result.forecast_paths:
    print(f"{path.scenario_name}: {path.probability:.0%}")
    for pt in path.path_points:
        print(f"  {pt['date']} → ${pt['price']:,.0f} ({pt['label']})")
```

### 실시간 업데이트

```python
from realtime_loop import RealtimeLoop

loop = RealtimeLoop('BTC-USD')
loop.initialize(timeframe_data)

# 새 캔들 도착 시
update = loop.on_new_candle({
    'date': datetime.now(),
    'open': 85000, 'high': 86000,
    'low': 83000, 'close': 84500,
    'volume': 30e9,
})

if update['invalidated']:
    print(f"무효화: {update['invalidated']}")
if update['alerts']:
    for alert in update['alerts']:
        print(alert['message'])
```

### 차트 생성

```python
from wave_chart import WaveChart

chart = WaveChart()
chart.plot(
    df=ohlcv_dataframe,
    waves=wave_points,
    forecast_paths=result.forecast_paths,
    symbol='BTC-USD',
    timeframe='Daily',
    save_path='btc_forecast.png',
)
```

## TimeframeLinker 제약 규칙

| 규칙 | 설명 | 심각도 |
|------|------|--------|
| R1 | 상위/하위 프레임 방향 일치 | warning |
| R2 | 하위 가격 범위가 상위 범위 내 포함 | info |
| R3 | Wave 4가 Wave 1 영역 비침범 | **critical** |
| R4 | 하위 5파 완료 → 상위 전환 신호 | info |
| R5 | 하위/상위 범위 비율 일관성 | warning |

## 테스트

```bash
# 전체 테스트 (93개)
python -m pytest tests/ -v

# 예측 시스템만
python -m pytest tests/test_forecast_system.py -v
```

## 버전

| 버전 | 내용 |
|------|------|
| v1.0.0 | 기초 파동 분석 + 12패턴 |
| v2.0.0 | 시나리오 무효화, 70 테스트 |
| v2.1.0 | HTML 대시보드 리포트 |
| v2.2.0 | 봉차트 + 파동 카운트 시각화 |
| **v3.0.0** | **ForecastEngine + TimeframeLinker + RealtimeLoop + 미래 경로 시각화** |
