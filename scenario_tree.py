"""
Scenario Tree - 다중 시나리오 관리 및 확률 업데이트
==================================================
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json
import math

from experts.elliott.live_tracker import (
    WaveScenarioLive, WaveType, WavePosition,
    InvalidationRule, TargetLevel, MarketState, TrackingResult
)


class ScenarioTree:
    """
    다중 Elliott Wave 시나리오 관리
    
    - 여러 해석 동시 추적
    - 무효화 자동 감지
    - 확률 정규화
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.scenarios: Dict[str, WaveScenarioLive] = {}
        self.history: List[Dict] = []
        self.created_at = datetime.now()
        
    def add_scenario(self, scenario: WaveScenarioLive) -> None:
        """시나리오 추가"""
        self.scenarios[scenario.id] = scenario
        self._normalize_probabilities()
        
    def remove_scenario(self, scenario_id: str) -> None:
        """시나리오 제거"""
        if scenario_id in self.scenarios:
            del self.scenarios[scenario_id]
            self._normalize_probabilities()
    
    def update_with_price(self, current_price: float) -> List[str]:
        """
        새 가격으로 모든 시나리오 업데이트
        
        Returns:
            무효화된 시나리오 ID 목록
        """
        invalidated = []
        
        for scenario_id, scenario in self.scenarios.items():
            if scenario.check_invalidation(current_price):
                invalidated.append(scenario_id)
                self.history.append({
                    'timestamp': datetime.now().isoformat(),
                    'event': 'invalidation',
                    'scenario_id': scenario_id,
                    'price': current_price,
                    'reason': scenario.invalidation_reason
                })
        
        if invalidated:
            self._normalize_probabilities()
        
        return invalidated
    
    def get_valid_scenarios(self) -> List[WaveScenarioLive]:
        """유효한 시나리오들"""
        return [s for s in self.scenarios.values() if s.is_valid]
    
    def get_primary_scenario(self) -> Optional[WaveScenarioLive]:
        """가장 확률 높은 시나리오"""
        valid = self.get_valid_scenarios()
        if not valid:
            return None
        return max(valid, key=lambda s: s.probability)
    
    def _normalize_probabilities(self) -> None:
        """확률 정규화 (합 = 1.0)"""
        valid_scenarios = self.get_valid_scenarios()
        if not valid_scenarios:
            return
        
        total_prob = sum(s.probability for s in valid_scenarios)
        if total_prob > 0:
            for s in valid_scenarios:
                s.probability = s.probability / total_prob
    
    def get_summary(self) -> Dict:
        """요약"""
        valid = self.get_valid_scenarios()
        primary = self.get_primary_scenario()
        
        return {
            'symbol': self.symbol,
            'total_scenarios': len(self.scenarios),
            'valid_scenarios': len(valid),
            'primary': primary.name if primary else None,
            'primary_probability': primary.probability if primary else 0,
            'scenarios': [
                {'id': s.id, 'name': s.name, 'prob': s.probability, 'valid': s.is_valid}
                for s in self.scenarios.values()
            ]
        }


class ProbabilityEngine:
    """
    베이지안 확률 업데이트 엔진
    
    - 기술적 확인으로 확률 조정
    - 피보나치 반응 가중치
    """
    
    # 확률 조정 가중치
    FIB_BOUNCE_WEIGHT = 1.3      # 피보나치 레벨에서 반등
    FIB_BREAK_WEIGHT = 0.7       # 피보나치 레벨 이탈
    VOLUME_CONFIRM_WEIGHT = 1.2  # 볼륨 확인
    RSI_DIVERGENCE_WEIGHT = 1.4  # RSI 다이버전스
    
    # 주요 피보나치 레벨
    FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618, 2.618]
    
    def __init__(self):
        self.update_log: List[Dict] = []
    
    def update_probability(
        self,
        scenario: WaveScenarioLive,
        market_state: MarketState,
        events: List[str] = None
    ) -> float:
        """
        시나리오 확률 업데이트
        
        Args:
            scenario: 업데이트할 시나리오
            market_state: 현재 시장 상태
            events: 발생한 이벤트들 ['fib_bounce', 'volume_spike', 'rsi_divergence']
        
        Returns:
            새 확률
        """
        if not scenario.is_valid:
            return 0.0
        
        current_prob = scenario.probability
        multiplier = 1.0
        
        events = events or []
        
        # 이벤트 기반 조정
        if 'fib_bounce' in events:
            multiplier *= self.FIB_BOUNCE_WEIGHT
        if 'fib_break' in events:
            multiplier *= self.FIB_BREAK_WEIGHT
        if 'volume_confirm' in events:
            multiplier *= self.VOLUME_CONFIRM_WEIGHT
        if 'rsi_divergence' in events:
            multiplier *= self.RSI_DIVERGENCE_WEIGHT
        
        # 가격 위치 기반 조정
        position_factor = self._calc_position_factor(scenario, market_state.current_price)
        multiplier *= position_factor
        
        new_prob = min(0.95, max(0.05, current_prob * multiplier))
        
        # 로그
        if abs(new_prob - current_prob) > 0.01:
            self.update_log.append({
                'timestamp': datetime.now().isoformat(),
                'scenario_id': scenario.id,
                'old_prob': current_prob,
                'new_prob': new_prob,
                'multiplier': multiplier,
                'events': events
            })
        
        scenario.probability = new_prob
        scenario.updated_at = datetime.now().isoformat()
        
        return new_prob
    
    def _calc_position_factor(
        self,
        scenario: WaveScenarioLive,
        current_price: float
    ) -> float:
        """시나리오 예측과 현재 가격 간 정합성"""
        # 목표가 방향과 가격 움직임 비교
        if not scenario.targets:
            return 1.0
        
        primary_target = scenario.targets[0].price
        
        # 가장 최근 파동 가격
        if scenario.waves:
            last_wave_price = scenario.waves[-1].get('price', current_price)
            
            # 상승 시나리오인데 가격이 하락 중
            if primary_target > last_wave_price and current_price < last_wave_price:
                return 0.9
            # 하락 시나리오인데 가격이 상승 중
            elif primary_target < last_wave_price and current_price > last_wave_price:
                return 0.9
        
        return 1.0
    
    def detect_events(
        self,
        market_state: MarketState,
        scenario: WaveScenarioLive
    ) -> List[str]:
        """시장 이벤트 감지"""
        events = []
        price = market_state.current_price
        
        # 피보나치 레벨 근접 체크
        for level_name, level_price in market_state.fib_levels.items():
            tolerance = level_price * 0.02  # 2% 허용
            if abs(price - level_price) < tolerance:
                # 반등인지 이탈인지 판단 (간단한 휴리스틱)
                events.append('fib_bounce')  # 실제로는 더 정교한 로직 필요
                break
        
        # RSI 과매수/과매도
        if market_state.rsi:
            if market_state.rsi > 70:
                events.append('overbought')
            elif market_state.rsi < 30:
                events.append('oversold')
        
        # 볼륨 트렌드
        if market_state.volume_trend == 'increasing':
            events.append('volume_confirm')
        
        return events


class FibonacciCalculator:
    """피보나치 레벨 계산"""
    
    RETRACEMENT_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
    EXTENSION_LEVELS = [1.0, 1.272, 1.618, 2.0, 2.618, 3.618]
    
    @staticmethod
    def calc_retracement(high: float, low: float) -> Dict[str, float]:
        """되돌림 레벨 계산"""
        diff = high - low
        return {
            f"fib_{int(level*1000)}": high - (diff * level)
            for level in FibonacciCalculator.RETRACEMENT_LEVELS
        }
    
    @staticmethod
    def calc_extension(
        wave_0: float,
        wave_1: float,
        wave_2: float
    ) -> Dict[str, float]:
        """확장 레벨 계산 (Wave 2에서 시작)"""
        wave_1_length = abs(wave_1 - wave_0)
        direction = 1 if wave_1 > wave_0 else -1
        
        return {
            f"ext_{int(level*1000)}": wave_2 + (wave_1_length * level * direction)
            for level in FibonacciCalculator.EXTENSION_LEVELS
        }
    
    @staticmethod
    def calc_wave_targets(waves: List[Dict]) -> List[TargetLevel]:
        """파동 기반 목표가 계산"""
        targets = []
        
        wave_map = {w['label']: w for w in waves}
        
        # Wave 3 목표 (Wave 1 기준)
        if all(k in wave_map for k in ['0', '1', '2']):
            w0 = wave_map['0']['price']
            w1 = wave_map['1']['price']
            w2 = wave_map['2']['price']
            
            w1_len = abs(w1 - w0)
            direction = 1 if w1 > w0 else -1
            
            for ratio, prob in [(1.618, 0.6), (2.0, 0.25), (2.618, 0.15)]:
                target_price = w2 + (w1_len * ratio * direction)
                targets.append(TargetLevel(
                    price=target_price,
                    probability=prob,
                    fib_ratio=ratio,
                    description=f"Wave 3 target ({ratio}x W1)"
                ))
        
        # Wave 5 목표 (Wave 3 완료 후)
        if all(k in wave_map for k in ['0', '1', '2', '3', '4']):
            w0 = wave_map['0']['price']
            w1 = wave_map['1']['price']
            w3 = wave_map['3']['price']
            w4 = wave_map['4']['price']
            
            w1_len = abs(w1 - w0)
            direction = 1 if w1 > w0 else -1
            
            # Wave 5 = Wave 1 (가장 일반적)
            targets.append(TargetLevel(
                price=w4 + (w1_len * direction),
                probability=0.5,
                fib_ratio=1.0,
                description="Wave 5 = Wave 1"
            ))
            
            # Wave 5 = 0.618 * Wave 1
            targets.append(TargetLevel(
                price=w4 + (w1_len * 0.618 * direction),
                probability=0.3,
                fib_ratio=0.618,
                description="Wave 5 = 0.618 × Wave 1"
            ))
        
        return targets
