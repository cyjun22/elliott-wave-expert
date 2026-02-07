"""
Adaptive Wave Tracker - 실시간 파동 재분류 시스템
================================================

핵심 기능:
- 확정 파동 vs 임시 파동 분리
- 새 캔들 추가시 자동 재분류
- 무효화 레벨 돌파 시 시나리오 자동 전환
- 롤백 및 대안 카운트 탐색

Based on: ElliottAgents research, WaveBasis patterns
"""

import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WaveStatus(Enum):
    """파동 확정 상태"""
    CONFIRMED = "confirmed"      # 확정 (변경 불가)
    TENTATIVE = "tentative"      # 임시 (재분류 가능)
    INVALIDATED = "invalidated"  # 무효화됨


@dataclass
class WavePoint:
    """개별 파동 포인트"""
    label: str
    price: float
    date: datetime
    status: WaveStatus = WaveStatus.TENTATIVE
    confidence: float = 0.5


@dataclass
class ScenarioState:
    """시나리오 상태"""
    scenario_id: str
    name: str
    probability: float
    is_active: bool = True
    invalidation_price: Optional[float] = None
    invalidation_type: str = ""  # 'price_above', 'price_below'


class AdaptiveWaveTracker:
    """
    적응형 파동 추적기
    
    실시간 데이터로 파동 구조를 동적으로 업데이트
    """
    
    def __init__(self, symbol: str, buffer_size: int = 100):
        self.symbol = symbol
        self.buffer_size = buffer_size
        
        # 파동 저장소
        self.confirmed_waves: Dict[str, WavePoint] = {}  # 확정 파동
        self.tentative_waves: Dict[str, WavePoint] = {}  # 임시 파동
        self.wave_history: List[Dict] = []  # 변경 이력
        
        # 시나리오 관리
        self.active_scenarios: List[ScenarioState] = []
        self.invalidated_scenarios: List[ScenarioState] = []
        
        # 캔들 버퍼
        self.candle_buffer: List[Dict] = []
        
        # 상태
        self.last_update: Optional[datetime] = None
        self.current_phase: str = "unknown"
        
    def add_candle(self, candle: Dict) -> Dict:
        """
        새 캔들 추가 및 재분류
        
        Args:
            candle: {'date': datetime, 'open': float, 'high': float, 
                     'low': float, 'close': float, 'volume': float}
        
        Returns:
            결과 딕셔너리: 재분류 여부, 변경 사항 등
        """
        self.candle_buffer.append(candle)
        
        # 버퍼 크기 제한
        if len(self.candle_buffer) > self.buffer_size:
            self.candle_buffer.pop(0)
        
        current_price = candle['close']
        result = {
            'reclassified': False,
            'invalidated_scenarios': [],
            'switched_to': None,
            'warnings': []
        }
        
        # 1. 무효화 레벨 체크
        invalidations = self._check_invalidations(current_price)
        if invalidations:
            result['invalidated_scenarios'] = invalidations
            result['reclassified'] = True
            
            # 시나리오 자동 전환
            new_scenario = self._switch_scenario(invalidations)
            if new_scenario:
                result['switched_to'] = new_scenario
        
        # 2. 임시 파동 재분류
        if self._should_reclassify(candle):
            self._reclassify_tentative_waves(candle)
            result['reclassified'] = True
        
        # 3. 상태 업데이트
        self.last_update = candle['date']
        self._update_current_phase(current_price)
        
        return result
    
    def _check_invalidations(self, current_price: float) -> List[str]:
        """무효화 조건 확인"""
        invalidated = []
        
        for scenario in self.active_scenarios:
            if not scenario.is_active:
                continue
                
            if scenario.invalidation_price is None:
                continue
            
            triggered = False
            if scenario.invalidation_type == 'price_above':
                triggered = current_price > scenario.invalidation_price
            elif scenario.invalidation_type == 'price_below':
                triggered = current_price < scenario.invalidation_price
            
            if triggered:
                scenario.is_active = False
                invalidated.append(scenario.name)
                self.invalidated_scenarios.append(scenario)
                
                # 이력 기록
                self.wave_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'event': 'scenario_invalidated',
                    'scenario': scenario.name,
                    'trigger_price': current_price,
                    'threshold': scenario.invalidation_price
                })
        
        # 무효화된 시나리오 제거
        self.active_scenarios = [s for s in self.active_scenarios if s.is_active]
        
        return invalidated
    
    def _switch_scenario(self, invalidated: List[str]) -> Optional[str]:
        """시나리오 자동 전환"""
        if not self.active_scenarios:
            return None
        
        # ABC Correction 무효화 시 → Extended 5th 활성화
        if "ABC Correction" in invalidated:
            for s in self.active_scenarios:
                if "Extended" in s.name:
                    s.probability = 0.7  # 확률 상향
                    return s.name
        
        # Extended 5th 무효화 시 → ABC Correction 활성화
        if "Extended 5th" in invalidated:
            for s in self.active_scenarios:
                if "ABC" in s.name or "Correction" in s.name:
                    s.probability = 0.7
                    return s.name
        
        # 남은 시나리오 중 가장 높은 확률
        if self.active_scenarios:
            best = max(self.active_scenarios, key=lambda x: x.probability)
            return best.name
        
        return None
    
    def _should_reclassify(self, candle: Dict) -> bool:
        """재분류 필요 여부 판단"""
        if len(self.candle_buffer) < 5:
            return False
        
        # 최근 5개 캔들의 평균 변동성
        recent = self.candle_buffer[-5:]
        avg_range = sum(c['high'] - c['low'] for c in recent) / 5
        
        # 현재 캔들이 평균의 2배 이상 → 재분류
        current_range = candle['high'] - candle['low']
        
        return current_range > avg_range * 2
    
    def _reclassify_tentative_waves(self, trigger_candle: Dict):
        """임시 파동 재분류"""
        current_price = trigger_candle['close']
        
        # 임시 파동들을 현재가 기준으로 재평가
        labels_to_remove = []
        
        for label, wave in self.tentative_waves.items():
            # 파동이 현재가보다 너무 멀면 재분류
            distance = abs(wave.price - current_price) / current_price
            
            if distance > 0.5:  # 50% 이상 차이
                labels_to_remove.append(label)
                self.wave_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'event': 'wave_reclassified',
                    'label': label,
                    'old_price': wave.price,
                    'trigger_price': current_price
                })
        
        # 제거
        for label in labels_to_remove:
            del self.tentative_waves[label]
    
    def _update_current_phase(self, current_price: float):
        """현재 단계 업데이트"""
        all_waves = {**self.confirmed_waves, **self.tentative_waves}
        
        if not all_waves:
            self.current_phase = "unknown"
            return
        
        # 가장 최근 파동
        labels = list(all_waves.keys())
        last_label = labels[-1] if labels else None
        
        if last_label in ['0', '1', '2', '3', '4']:
            self.current_phase = f"impulse_{last_label}"
        elif last_label == '5':
            self.current_phase = "impulse_complete"
        elif last_label in ['A', 'B', 'C']:
            self.current_phase = f"correction_{last_label}"
        else:
            self.current_phase = "unknown"
    
    def confirm_wave(self, label: str):
        """파동 확정"""
        if label in self.tentative_waves:
            wave = self.tentative_waves.pop(label)
            wave.status = WaveStatus.CONFIRMED
            self.confirmed_waves[label] = wave
            
            self.wave_history.append({
                'timestamp': datetime.now().isoformat(),
                'event': 'wave_confirmed',
                'label': label,
                'price': wave.price
            })
    
    def rollback_to_last_confirmed(self) -> int:
        """마지막 확정 파동으로 롤백"""
        removed_count = len(self.tentative_waves)
        
        self.wave_history.append({
            'timestamp': datetime.now().isoformat(),
            'event': 'rollback',
            'removed_waves': list(self.tentative_waves.keys())
        })
        
        self.tentative_waves.clear()
        
        return removed_count
    
    def set_scenarios(self, scenarios: List[Dict]):
        """시나리오 설정"""
        self.active_scenarios = []
        
        for s in scenarios:
            self.active_scenarios.append(ScenarioState(
                scenario_id=s.get('id', ''),
                name=s.get('name', ''),
                probability=s.get('probability', 0.0),
                is_active=True,
                invalidation_price=s.get('invalidation_price'),
                invalidation_type=s.get('invalidation_type', 'price_above')
            ))
    
    def get_status(self) -> Dict:
        """현재 상태 반환"""
        return {
            'symbol': self.symbol,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'current_phase': self.current_phase,
            'confirmed_waves': len(self.confirmed_waves),
            'tentative_waves': len(self.tentative_waves),
            'active_scenarios': len(self.active_scenarios),
            'invalidated_scenarios': len(self.invalidated_scenarios),
            'buffer_size': len(self.candle_buffer),
            'history_events': len(self.wave_history)
        }
    
    def get_wave_summary(self) -> Dict:
        """파동 요약"""
        all_waves = {**self.confirmed_waves, **self.tentative_waves}
        
        return {
            label: {
                'price': wave.price,
                'date': wave.date.isoformat() if isinstance(wave.date, datetime) else wave.date,
                'status': wave.status.value,
                'confidence': wave.confidence
            }
            for label, wave in all_waves.items()
        }


# 테스트
def test_adaptive_tracker():
    """적응형 추적기 테스트"""
    tracker = AdaptiveWaveTracker('BTC-USD')
    
    # 시나리오 설정
    tracker.set_scenarios([
        {
            'id': 'abc_correction',
            'name': 'ABC Correction',
            'probability': 0.7,
            'invalidation_price': 111180,  # ATH * 1.02
            'invalidation_type': 'price_above'
        },
        {
            'id': 'extended_5th',
            'name': 'Extended 5th Wave',
            'probability': 0.06,
            'invalidation_price': 56000,  # W4
            'invalidation_type': 'price_below'
        }
    ])
    
    # 테스트 캔들
    test_candles = [
        {'date': datetime(2025, 2, 1), 'open': 97000, 'high': 98000, 'low': 96000, 'close': 97500, 'volume': 1000},
        {'date': datetime(2025, 2, 2), 'open': 97500, 'high': 99000, 'low': 97000, 'close': 98500, 'volume': 1200},
        {'date': datetime(2025, 2, 3), 'open': 98500, 'high': 100000, 'low': 98000, 'close': 99000, 'volume': 1100},
        # ATH 돌파 테스트
        {'date': datetime(2025, 2, 4), 'open': 99000, 'high': 112000, 'low': 99000, 'close': 111500, 'volume': 2000},
    ]
    
    print("=== 적응형 추적기 테스트 ===\n")
    
    for candle in test_candles:
        result = tracker.add_candle(candle)
        print(f"📊 {candle['date'].strftime('%Y-%m-%d')}: ${candle['close']:,.0f}")
        
        if result['invalidated_scenarios']:
            print(f"   ❌ 무효화: {result['invalidated_scenarios']}")
        if result['switched_to']:
            print(f"   🔄 전환: {result['switched_to']}")
        if result['reclassified']:
            print(f"   🔃 재분류 실행")
    
    print(f"\n📋 최종 상태: {tracker.get_status()}")
    
    return tracker


if __name__ == '__main__':
    test_adaptive_tracker()
