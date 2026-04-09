"""
ForecastEngine - 통합 시나리오 예측 파이프라인
===============================================

핵심 역할:
  실시간 데이터 → 파동 분석 → 시나리오 생성 → 미래 예측 → 확률 업데이트
  모든 기존 모듈(ScenarioGenerator, ScenarioTree, ProbabilityEngine,
  AdaptiveTracker, TimeframeLinker)을 하나의 파이프라인으로 통합.

사용법:
  engine = ForecastEngine('BTC-USD')
  result = engine.run_full_pipeline(ohlcv_data_dict)
  # result.scenarios, result.primary_scenario, result.forecast_paths 등

v3.0.0 — 2026-04-09
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import math

from experts.elliott.live_tracker import (
    WaveScenarioLive, WaveType, WavePosition,
    InvalidationRule, TargetLevel, MarketState, TrackingResult
)
from experts.elliott.wave_scenarios import (
    ScenarioGenerator, WaveInterpretation, ScenarioWithInvalidation
)
from experts.elliott.scenario_tree import (
    ScenarioTree, ProbabilityEngine, FibonacciCalculator
)
from experts.elliott.adaptive_tracker import (
    AdaptiveWaveTracker, ScenarioState, WavePoint, WaveStatus
)
from experts.elliott.timeframe_linker import TimeframeLinker


# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────

@dataclass
class ForecastPath:
    """단일 미래 시나리오 경로"""
    scenario_id: str
    scenario_name: str
    probability: float
    path_points: List[Dict]     # [{'date': ..., 'price': ..., 'label': ...}, ...]
    invalidation_price: float
    invalidation_direction: str  # 'above' / 'below'
    targets: List[Dict]         # [{'price': ..., 'fib': ..., 'desc': ...}]
    confidence: float
    wave_type: str              # 'impulse' / 'corrective'


@dataclass
class ForecastResult:
    """ForecastEngine 전체 출력"""
    symbol: str
    timestamp: datetime
    current_price: float

    # 시나리오 + 예측 경로
    scenarios: List[WaveScenarioLive]
    forecast_paths: List[ForecastPath]
    primary_scenario: Optional[WaveScenarioLive]

    # 멀티타임프레임 합의
    timeframe_consensus: Dict       # {'aligned_phase': ..., 'confidence': ..., 'details': ...}

    # 핵심 레벨
    key_levels: Dict[str, float]    # {'invalidation': ..., 'target_1': ..., 'stop_loss': ...}

    # 메타
    interpretations: List[WaveInterpretation]
    update_log: List[Dict]
    overall_bias: str               # 'bullish' / 'bearish' / 'neutral'

    def get_best_path(self) -> Optional[ForecastPath]:
        """가장 높은 확률의 예측 경로"""
        valid = [p for p in self.forecast_paths if p.probability > 0]
        return max(valid, key=lambda p: p.probability) if valid else None


# ─────────────────────────────────────────────────────────────
# ForecastEngine
# ─────────────────────────────────────────────────────────────

class ForecastEngine:
    """
    통합 시나리오 예측 엔진

    파이프라인 단계:
      1. 멀티타임프레임 피벗 추출
      2. 각 타임프레임 파동 분석 → TimeframeLinker 교차 제약
      3. ScenarioGenerator로 시나리오 해석 생성
      4. ScenarioTree + ProbabilityEngine으로 확률 관리
      5. 미래 예측 경로(ForecastPath) 생성
      6. AdaptiveTracker에 시나리오 등록 (실시간 업데이트용)
    """

    def __init__(self, symbol: str = 'BTC-USD'):
        self.symbol = symbol

        # 하위 모듈
        self.scenario_gen = ScenarioGenerator()
        self.scenario_tree = ScenarioTree(symbol)
        self.prob_engine = ProbabilityEngine()
        self.adaptive_tracker = AdaptiveWaveTracker(symbol)
        self.timeframe_linker = TimeframeLinker()
        self.fib_calc = FibonacciCalculator()

        # 상태
        self._last_result: Optional[ForecastResult] = None
        self._update_count: int = 0

    # ─── public API ────────────────────────────────────────

    def run_full_pipeline(
        self,
        timeframe_data: Dict[str, List[Dict]],
        current_price: Optional[float] = None,
    ) -> ForecastResult:
        """
        전체 파이프라인 1회 실행.

        Args:
            timeframe_data: 타임프레임별 OHLCV 리스트
                {
                  '1d': [{'date':..,'open':..,'high':..,'low':..,'close':..,'volume':..}, ...],
                  '4h': [...],
                  '1h': [...]
                }
            current_price: 현재가 (None이면 가장 최근 close 사용)

        Returns:
            ForecastResult
        """
        self._update_count += 1
        timestamp = datetime.now()

        # 0) 현재가 결정
        if current_price is None:
            for tf in ['1h', '4h', '1d']:
                if tf in timeframe_data and timeframe_data[tf]:
                    current_price = timeframe_data[tf][-1]['close']
                    break
        if current_price is None:
            raise ValueError("current_price를 결정할 수 없습니다. 데이터를 확인하세요.")

        # 1) 각 타임프레임 피벗 추출
        tf_pivots: Dict[str, List[Dict]] = {}
        for tf, candles in timeframe_data.items():
            tf_pivots[tf] = self._extract_pivots(candles, tf)

        # 2) TimeframeLinker 교차 검증
        link_result = self.timeframe_linker.link_timeframes(tf_pivots, current_price)

        # 3) 대프레임(daily) 피벗으로 시나리오 해석 생성
        daily_pivots = tf_pivots.get('1d', tf_pivots.get(list(tf_pivots.keys())[0]))
        interpretations = self.scenario_gen.generate_interpretations(
            daily_pivots, current_price
        )

        # 4) WaveScenarioLive 변환 → ScenarioTree 등록
        self.scenario_tree = ScenarioTree(self.symbol)  # 리셋
        scenarios: List[WaveScenarioLive] = []
        for interp in interpretations:
            scenario = self._interpretation_to_scenario(interp, current_price)
            scenarios.append(scenario)
            self.scenario_tree.add_scenario(scenario)

        # 5) 타임프레임 제약으로 확률 보정
        self._apply_timeframe_constraints(scenarios, link_result)

        # 6) 무효화 체크
        invalidated = self.scenario_tree.update_with_price(current_price)

        # 7) 예측 경로 생성
        forecast_paths = self._build_forecast_paths(
            interpretations, scenarios, current_price, timestamp
        )

        # 8) AdaptiveTracker에 등록
        self._sync_adaptive_tracker(scenarios)

        # 9) 핵심 레벨 집계
        primary = self.scenario_tree.get_primary_scenario()
        key_levels = self._aggregate_key_levels(scenarios, current_price)

        # 10) 전체 바이어스
        bias = self._determine_overall_bias(scenarios, current_price)

        result = ForecastResult(
            symbol=self.symbol,
            timestamp=timestamp,
            current_price=current_price,
            scenarios=scenarios,
            forecast_paths=forecast_paths,
            primary_scenario=primary,
            timeframe_consensus={
                'aligned_phase': link_result.get('consensus_phase', 'unknown'),
                'confidence': link_result.get('confidence', 0.0),
                'valid_links': link_result.get('valid_links', 0),
                'total_links': link_result.get('total_links', 0),
                'constraint_violations': link_result.get('violations', []),
            },
            key_levels=key_levels,
            interpretations=interpretations,
            update_log=self.prob_engine.update_log[-10:],
            overall_bias=bias,
        )
        self._last_result = result
        return result

    def update_with_candle(self, candle: Dict) -> Dict:
        """
        새 캔들 1개로 실시간 업데이트.

        AdaptiveTracker에 캔들 추가 → 무효화/재분류 → 확률 재계산.

        Args:
            candle: {'date':..,'open':..,'high':..,'low':..,'close':..,'volume':..}

        Returns:
            {
              'reclassified': bool,
              'invalidated': [str],
              'switched_to': str | None,
              'probabilities': {scenario_id: float, ...}
            }
        """
        tracker_result = self.adaptive_tracker.add_candle(candle)

        # ScenarioTree에도 가격 반영
        price = candle['close']
        tree_invalidated = self.scenario_tree.update_with_price(price)

        # MarketState 간이 생성
        ms = MarketState(
            symbol=self.symbol,
            current_price=price,
            timestamp=candle['date'] if isinstance(candle['date'], datetime) else datetime.now(),
        )

        # 유효 시나리오 확률 재계산
        probs = {}
        for sc in self.scenario_tree.get_valid_scenarios():
            events = self.prob_engine.detect_events(ms, sc)
            new_p = self.prob_engine.update_probability(sc, ms, events)
            probs[sc.id] = new_p

        # 정규화
        self.scenario_tree._normalize_probabilities()

        return {
            'reclassified': tracker_result['reclassified'],
            'invalidated': tracker_result['invalidated_scenarios'] + tree_invalidated,
            'switched_to': tracker_result.get('switched_to'),
            'probabilities': probs,
        }

    def get_current_forecast(self) -> Optional[ForecastResult]:
        """마지막 파이프라인 결과"""
        return self._last_result

    # ─── private helpers ───────────────────────────────────

    def _extract_pivots(
        self, candles: List[Dict], timeframe: str
    ) -> List[Dict]:
        """
        캔들 데이터에서 주요 피벗(고점/저점) 추출.
        window 크기를 타임프레임에 따라 조절.
        """
        if not candles:
            return []

        tf_window = {'1d': 10, '4h': 8, '1h': 6}.get(timeframe, 8)
        window = min(tf_window, max(3, len(candles) // 10))

        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        pivots: List[Dict] = []
        n = len(candles)

        for i in range(window, n - window):
            # 로컬 최고점
            local_highs = highs[i - window: i + window + 1]
            if highs[i] == max(local_highs):
                pivots.append({
                    'date': candles[i]['date'] if isinstance(candles[i]['date'], str)
                            else candles[i]['date'].isoformat()
                            if isinstance(candles[i]['date'], datetime) else str(candles[i]['date']),
                    'price': highs[i],
                    'type': 'high',
                })
            # 로컬 최저점
            local_lows = lows[i - window: i + window + 1]
            if lows[i] == min(local_lows):
                pivots.append({
                    'date': candles[i]['date'] if isinstance(candles[i]['date'], str)
                            else candles[i]['date'].isoformat()
                            if isinstance(candles[i]['date'], datetime) else str(candles[i]['date']),
                    'price': lows[i],
                    'type': 'low',
                })

        # 날짜순 정렬 & 중복 제거 (같은 날짜/가격)
        pivots.sort(key=lambda p: p['date'])
        unique: List[Dict] = []
        for p in pivots:
            if not unique or (p['date'] != unique[-1]['date'] or p['price'] != unique[-1]['price']):
                unique.append(p)

        # 연속 같은 타입 제거 (high-high → 더 높은 것만)
        filtered: List[Dict] = []
        for p in unique:
            if filtered and filtered[-1]['type'] == p['type']:
                if p['type'] == 'high' and p['price'] > filtered[-1]['price']:
                    filtered[-1] = p
                elif p['type'] == 'low' and p['price'] < filtered[-1]['price']:
                    filtered[-1] = p
            else:
                filtered.append(p)

        return filtered

    def _interpretation_to_scenario(
        self, interp: WaveInterpretation, current_price: float
    ) -> WaveScenarioLive:
        """WaveInterpretation → WaveScenarioLive 변환"""
        # wave_type 결정
        if interp.scenario_id in ('zigzag_abc', 'expanded_flat'):
            wtype = WaveType.CORRECTIVE
        else:
            wtype = WaveType.IMPULSE

        # 현재 위치
        pos_map = {
            'A': WavePosition.WAVE_A, 'B': WavePosition.WAVE_B,
            'C': WavePosition.WAVE_C, 'C_ending': WavePosition.WAVE_C,
            'W4': WavePosition.WAVE_4, 'W5': WavePosition.WAVE_5,
        }
        position = pos_map.get(interp.current_wave, WavePosition.WAVE_C)

        # 무효화 규칙
        inv_rules = []
        if interp.invalidation_price > 0:
            direction = 'price_above' if wtype == WaveType.CORRECTIVE else 'price_below'
            inv_rules.append(InvalidationRule(
                condition_type=direction,
                threshold=interp.invalidation_price,
                description=f"{interp.scenario_name} 무효화: ${interp.invalidation_price:,.0f}",
            ))

        # 목표가
        targets = [
            TargetLevel(
                price=t['price'], probability=0.4,
                fib_ratio=t.get('fib', 0.0), description=t.get('desc', '')
            )
            for t in interp.targets
        ]

        return WaveScenarioLive(
            id=f"{self.symbol}_{interp.scenario_id}",
            name=interp.scenario_name,
            description=interp.description,
            wave_type=wtype,
            current_position=position,
            waves=interp.wave_labels,
            probability=interp.probability,
            confidence=interp.confidence,
            invalidation_rules=inv_rules,
            targets=targets,
            stop_loss=interp.invalidation_price,
            created_at=datetime.now().isoformat(),
        )

    def _apply_timeframe_constraints(
        self, scenarios: List[WaveScenarioLive], link_result: Dict
    ) -> None:
        """
        타임프레임 교차 제약으로 시나리오 확률 조정.
        일치하면 확률 ×1.2, 불일치하면 ×0.7.
        """
        violations = link_result.get('violations', [])
        confidence = link_result.get('confidence', 0.5)

        for sc in scenarios:
            if not sc.is_valid:
                continue

            # 교차 제약 위반이 많으면 해당 시나리오 확률 감소
            violation_count = sum(
                1 for v in violations
                if v.get('scenario_id') == sc.id or v.get('affects', '') == sc.name
            )
            if violation_count > 0:
                sc.probability *= max(0.3, 1.0 - violation_count * 0.15)
            elif confidence > 0.6:
                sc.probability *= 1.1  # 교차 확인 보너스

        # 재정규화
        total = sum(s.probability for s in scenarios if s.is_valid)
        if total > 0:
            for s in scenarios:
                if s.is_valid:
                    s.probability /= total

    def _build_forecast_paths(
        self,
        interpretations: List[WaveInterpretation],
        scenarios: List[WaveScenarioLive],
        current_price: float,
        timestamp: datetime,
    ) -> List[ForecastPath]:
        """해석별 미래 경로 생성"""
        paths: List[ForecastPath] = []

        for interp, sc in zip(interpretations, scenarios):
            if not sc.is_valid:
                continue

            # projected_path가 있으면 그대로 사용, 없으면 피보나치 기반 생성
            if interp.projected_path:
                points = interp.projected_path
            else:
                points = self._generate_fib_path(interp, current_price, timestamp)

            inv_dir = 'above' if sc.wave_type == WaveType.CORRECTIVE else 'below'

            paths.append(ForecastPath(
                scenario_id=sc.id,
                scenario_name=sc.name,
                probability=sc.probability,
                path_points=points,
                invalidation_price=interp.invalidation_price,
                invalidation_direction=inv_dir,
                targets=[
                    {'price': t.price, 'fib': t.fib_ratio, 'desc': t.description}
                    for t in sc.targets
                ],
                confidence=sc.confidence,
                wave_type=sc.wave_type.value,
            ))

        # 확률 순 정렬
        paths.sort(key=lambda p: p.probability, reverse=True)
        return paths

    def _generate_fib_path(
        self, interp: WaveInterpretation, current_price: float, timestamp: datetime
    ) -> List[Dict]:
        """피보나치 기반 기본 경로 생성"""
        points = [
            {'date': timestamp.isoformat(), 'price': current_price, 'label': '현재'}
        ]
        for t in interp.targets:
            days_offset = 30 if t.get('fib', 0) < 0.5 else 60
            target_date = timestamp + timedelta(days=days_offset)
            points.append({
                'date': target_date.isoformat(),
                'price': t['price'],
                'label': t.get('desc', ''),
            })
        return points

    def _sync_adaptive_tracker(self, scenarios: List[WaveScenarioLive]) -> None:
        """AdaptiveTracker에 시나리오 동기화"""
        tracker_scenarios = []
        for sc in scenarios:
            if not sc.is_valid:
                continue
            inv_price = sc.invalidation_rules[0].threshold if sc.invalidation_rules else None
            inv_type = sc.invalidation_rules[0].condition_type if sc.invalidation_rules else 'price_above'
            tracker_scenarios.append({
                'id': sc.id,
                'name': sc.name,
                'probability': sc.probability,
                'invalidation_price': inv_price,
                'invalidation_type': inv_type,
            })
        self.adaptive_tracker.set_scenarios(tracker_scenarios)

    def _aggregate_key_levels(
        self, scenarios: List[WaveScenarioLive], current_price: float
    ) -> Dict[str, float]:
        """핵심 레벨 집계"""
        levels: Dict[str, float] = {}

        valid = [s for s in scenarios if s.is_valid]
        if not valid:
            return levels

        # 가장 높은 확률 시나리오 기준
        primary = max(valid, key=lambda s: s.probability)

        if primary.invalidation_rules:
            levels['invalidation'] = primary.invalidation_rules[0].threshold
        if primary.targets:
            for i, t in enumerate(primary.targets):
                levels[f'target_{i+1}'] = t.price
        if primary.stop_loss:
            levels['stop_loss'] = primary.stop_loss

        return levels

    def _determine_overall_bias(
        self, scenarios: List[WaveScenarioLive], current_price: float
    ) -> str:
        """전체 시나리오의 가중 바이어스"""
        bullish_weight = 0.0
        bearish_weight = 0.0

        for sc in scenarios:
            if not sc.is_valid:
                continue
            if sc.wave_type == WaveType.IMPULSE:
                bullish_weight += sc.probability
            else:
                bearish_weight += sc.probability

        if bullish_weight > bearish_weight * 1.3:
            return 'bullish'
        elif bearish_weight > bullish_weight * 1.3:
            return 'bearish'
        return 'neutral'
