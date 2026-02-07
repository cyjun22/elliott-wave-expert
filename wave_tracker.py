"""
Elliott Wave Tracker - 통합 실시간 추적 시스템
=============================================
- DualAgentExpert와 통합
- 실시간 시나리오 업데이트
- Cascading 예측
- 영속 기록 저장 (NN 트레이닝용)
- 시나리오 경로 시각화
- 시나리오별 파동 재해석 (v5.2)
"""

import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class WaveInterpretation:
    """
    시나리오별 파동 해석
    
    동일한 가격 데이터에서 다른 파동 해석을 표현
    - Zigzag: W0-W5 완료 후 ABC 조정
    - Running Flat: W3까지 완료, 현재 W4 → W5 예상 (강세)
    - Expanded Flat: W5 완료, 확장형 B파 → 깊은 C파
    - Extended 5th: W5 서브파동 진행 중
    """
    scenario_id: str
    scenario_name: str
    description: str
    
    # 재해석된 파동 라벨 (실제 피벗에 매핑)
    wave_labels: List[Dict] = field(default_factory=list)
    
    # 현재 상태
    current_wave: str = ""
    current_sub_wave: str = ""
    
    # 예상 경로 (날짜, 가격)
    projected_path: List[Dict] = field(default_factory=list)
    
    # 목표 및 무효화
    targets: List[Dict] = field(default_factory=list)
    invalidation_price: float = 0.0
    
    # 확률
    probability: float = 0.0
    confidence: float = 0.0

# Local imports
from experts.elliott.live_tracker import (
    WaveScenarioLive, WaveType, WavePosition,
    InvalidationRule, TargetLevel, MarketState, TrackingResult
)
from experts.elliott.scenario_tree import (
    ScenarioTree, ProbabilityEngine, FibonacciCalculator
)
from experts.elliott.dual_agent_expert import DualAgentExpert
from experts.elliott.tracker_history import WaveTrackerHistory
from experts.elliott.scenario_chart import (
    create_scenario_path_chart, create_multi_timeframe_chart
)
from experts.elliott.retroactive_adjuster import (
    RetroactiveAdjuster, ScenarioGenerator as RetroScenarioGenerator,
    ConflictType, STANDARD_SCENARIOS
)

# LLM
try:
    from knowledge_core.gemini_client import GeminiClient, GeminiModel
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


class ScenarioGenerator:
    """
    다중 시나리오 자동 생성
    
    현재 파동 분석 결과를 바탕으로 가능한 시나리오들 생성
    - 현재가 위치 기반 동적 확률 계산
    - ABC 조정 진행도 추적
    - 새 상승파 시나리오 포함
    """
    
    def generate_from_analysis(
        self,
        waves: List[Dict],
        current_price: float,
        symbol: str
    ) -> List[WaveScenarioLive]:
        """분석 결과로부터 시나리오 생성"""
        scenarios = []
        
        wave_map = {w['label']: w for w in waves}
        num_waves = len(waves)
        
        if num_waves >= 6:  # 0-5 완료
            # 동적 확률 계산
            probs = self._calculate_dynamic_probability(wave_map, current_price)
            
            # ABC 조정 위치 탐지
            abc_position = self._detect_abc_position(wave_map, current_price)
            
            # 시나리오 1: ABC 조정 진행 중
            scenarios.append(self._create_correction_scenario(
                waves, current_price, symbol, probs['correction'], abc_position
            ))
            
            # 시나리오 2: 새로운 사이클 시작 (ABC 완료 후 상승)
            scenarios.append(self._create_new_cycle_scenario(
                waves, current_price, symbol, probs['new_cycle'], abc_position
            ))
            
            # 시나리오 3: 확장 5파 (ATH 갱신 가능)
            scenarios.append(self._create_extended_5th_scenario(
                waves, current_price, symbol, probs['extended_5th']
            ))
            
            # 시나리오 4: 새 상승파 시작 (ABC 완료 감지시)
            if abc_position in ['C_ending', 'completed']:
                scenarios.append(self._create_new_impulse_scenario(
                    waves, current_price, symbol, probs.get('new_impulse', 0.15)
                ))
        
        elif num_waves >= 5:  # Wave 4 완료
            scenarios.append(self._create_wave5_scenario(
                waves, current_price, symbol
            ))
        
        # 확률 정규화
        total = sum(s.probability for s in scenarios)
        if total > 0:
            for s in scenarios:
                s.probability /= total
        
        return scenarios
    
    def _calculate_dynamic_probability(
        self,
        wave_map: Dict,
        current_price: float
    ) -> Dict[str, float]:
        """
        현재가 위치 기반 동적 확률 계산
        
        W5 대비 현재가 위치로 각 시나리오 확률 조정
        """
        w5_price = wave_map.get('5', {}).get('price', current_price)
        w4_price = wave_map.get('4', {}).get('price', current_price * 0.8)
        w0_price = wave_map.get('0', {}).get('price', current_price * 0.3)
        
        # 현재가가 W5 대비 얼마나 하락했는지
        decline_ratio = 1 - (current_price / w5_price) if w5_price > 0 else 0
        
        # 피보나치 레벨 기준
        wave_range = w5_price - w0_price
        fib_382 = w5_price - (wave_range * 0.382)
        fib_618 = w5_price - (wave_range * 0.618)
        
        # 기본 확률
        prob_correction = 0.50
        prob_new_cycle = 0.25
        prob_extended = 0.20
        prob_new_impulse = 0.05
        
        # 현재가 위치에 따른 조정
        if current_price > w5_price * 0.95:
            # ATH 근처 → Extended 5th 확률 높음
            prob_extended = 0.45
            prob_correction = 0.35
            prob_new_cycle = 0.15
            prob_new_impulse = 0.05
        elif current_price > fib_382:
            # 38.2% 위 → 조정 초기
            prob_correction = 0.55
            prob_extended = 0.25
            prob_new_cycle = 0.15
            prob_new_impulse = 0.05
        elif current_price > fib_618:
            # 38.2% ~ 61.8% → 조정 진행 중
            prob_correction = 0.60
            prob_new_cycle = 0.20
            prob_extended = 0.10
            prob_new_impulse = 0.10
        else:
            # 61.8% 아래 → 조정 막바지, 새 상승 가능
            prob_correction = 0.45
            prob_new_cycle = 0.25
            prob_extended = 0.05
            prob_new_impulse = 0.25
        
        # ===== ATH 대비 하락률 기반 조정 (핵심 개선) =====
        # ATH에서 30%+ 하락하면 Extended 5th는 비현실적
        ath_drop_ratio = decline_ratio  # W5(ATH) 대비 하락률
        
        if ath_drop_ratio > 0.40:  # 40%+ 하락
            # Extended 5th 거의 불가능, ABC 조정 확정적
            prob_extended = 0.02
            prob_correction = max(prob_correction, 0.55)
            prob_new_impulse = min(prob_new_impulse + 0.10, 0.35)
            print(f"⚠️ ATH 대비 {ath_drop_ratio:.1%} 하락 → Extended 5th 확률 감소")
        elif ath_drop_ratio > 0.30:  # 30~40% 하락
            prob_extended = min(prob_extended, 0.05)
            prob_correction = max(prob_correction, 0.50)
            print(f"📉 ATH 대비 {ath_drop_ratio:.1%} 하락 → 조정 확률 상향")
        
        return {
            'correction': prob_correction,
            'new_cycle': prob_new_cycle,
            'extended_5th': prob_extended,
            'new_impulse': prob_new_impulse
        }
    
    def _detect_abc_position(
        self,
        wave_map: Dict,
        current_price: float
    ) -> str:
        """
        ABC 조정 진행도 추적
        
        Returns:
            'A_wave': Wave A 진행 중
            'B_wave': Wave B 반등 중
            'C_wave': Wave C 하락 중
            'C_ending': Wave C 막바지 (반등 임박)
            'completed': ABC 완료 추정
        """
        w5_price = wave_map.get('5', {}).get('price', current_price)
        w0_price = wave_map.get('0', {}).get('price', current_price * 0.3)
        
        wave_range = w5_price - w0_price
        fib_236 = w5_price - (wave_range * 0.236)
        fib_382 = w5_price - (wave_range * 0.382)
        fib_500 = w5_price - (wave_range * 0.500)
        fib_618 = w5_price - (wave_range * 0.618)
        fib_786 = w5_price - (wave_range * 0.786)
        
        # 현재가 위치로 ABC 단계 추정
        if current_price > fib_236:
            return 'A_wave'  # 아직 하락 초기
        elif current_price > fib_382:
            return 'A_wave'  # Wave A 진행 중
        elif current_price > fib_500:
            return 'B_wave'  # Wave B 구간 (반등 가능)
        elif current_price > fib_618:
            return 'C_wave'  # Wave C 진행 중
        elif current_price > fib_786:
            return 'C_ending'  # Wave C 막바지
        else:
            return 'completed'  # ABC 완료 가능성
    
    def generate_interpretations(
        self,
        pivots: List[Dict],
        current_price: float,
        current_date: datetime = None
    ) -> List[WaveInterpretation]:
        """
        시나리오별 파동 재해석 생성
        
        동일한 피벗 데이터에서 다른 파동 해석을 생성
        각 시나리오는 고유한 파동 라벨, 현재 상태, 예상 경로를 가짐
        
        Args:
            pivots: 원시 피벗 데이터 [{'date': ..., 'price': ..., 'type': 'high'/'low'}, ...]
            current_price: 현재 가격
            current_date: 현재 날짜
        
        Returns:
            List[WaveInterpretation]: 시나리오별 재해석된 파동 구조
        """
        if current_date is None:
            current_date = datetime.now()
        
        interpretations = []
        
        # 피벗이 충분하지 않으면 빈 리스트 반환
        if len(pivots) < 6:
            return interpretations
        
        # 기준 피벗 (인덱스로 접근)
        # pivots[0] = 최저점 (W0), pivots[-1] = 최고점 또는 최근 피벗
        base_low = pivots[0]['price']
        base_date = datetime.fromisoformat(pivots[0]['date']) if isinstance(pivots[0]['date'], str) else pivots[0]['date']
        
        # ATH 피벗 찾기
        ath_pivot = max(pivots, key=lambda p: p['price'])
        ath_price = ath_pivot['price']
        ath_date = datetime.fromisoformat(ath_pivot['date']) if isinstance(ath_pivot['date'], str) else ath_pivot['date']
        
        # 피보나치 레벨
        wave_range = ath_price - base_low
        fib_382 = ath_price - (wave_range * 0.382)
        fib_500 = ath_price - (wave_range * 0.500)
        fib_618 = ath_price - (wave_range * 0.618)
        fib_786 = ath_price - (wave_range * 0.786)
        
        # 동적 확률 계산
        probs = self._calculate_dynamic_probability(
            {'5': {'price': ath_price}, '0': {'price': base_low}},
            current_price
        )
        
        # ========================================
        # 시나리오 1: Zigzag ABC (W5 → ABC 조정)
        # ========================================
        zigzag = self._interpret_zigzag(
            pivots, current_price, current_date,
            ath_price, ath_date, fib_382, fib_618, probs['correction']
        )
        interpretations.append(zigzag)
        
        # ========================================
        # 시나리오 2: Running Flat (강세 확산)
        # ATH = W3, 현재 = W4, 더 높은 W5 예상
        # ========================================
        running = self._interpret_running_flat(
            pivots, current_price, current_date,
            ath_price, ath_date, probs['new_cycle']
        )
        interpretations.append(running)
        
        # ========================================
        # 시나리오 3: Expanded Flat (확장형 플랫)
        # B파가 ATH 터치, C파 깊은 조정
        # ========================================
        expanded = self._interpret_expanded_flat(
            pivots, current_price, current_date,
            ath_price, ath_date, fib_786, probs.get('new_impulse', 0.15)
        )
        interpretations.append(expanded)
        
        # ========================================
        # 시나리오 4: Extended 5th (5파 확장)
        # ========================================
        extended = self._interpret_extended_5th(
            pivots, current_price, current_date,
            ath_price, ath_date, probs['extended_5th']
        )
        interpretations.append(extended)
        
        # 확률 정규화
        total = sum(i.probability for i in interpretations)
        if total > 0:
            for i in interpretations:
                i.probability /= total
        
        return interpretations
    
    def _interpret_zigzag(
        self, pivots, current_price, current_date,
        ath_price, ath_date, fib_382, fib_618, probability
    ) -> WaveInterpretation:
        """Zigzag ABC 해석: W0-W5 완료 후 ABC 조정"""
        # 기존 피벗을 W0-W5로 라벨링
        labels = []
        wave_names = ['W0', 'W1', 'W2', 'W3', 'W4', 'W5']
        for i, p in enumerate(pivots[:6]):
            labels.append({
                'label': wave_names[i],
                'date': p['date'],
                'price': p['price']
            })
        
        # ABC 추가 (예상 경로)
        a_date = ath_date + timedelta(days=45)
        b_date = ath_date + timedelta(days=90)
        c_target = fib_618
        c_date = current_date + timedelta(days=45)
        
        # 현재 위치 판단
        if current_price > fib_382:
            current_wave = 'A'
            desc = f"Wave A 하락 진행 중. 현재 ${current_price:,.0f}"
        elif current_price > fib_618:
            current_wave = 'C'
            desc = f"Wave C 하락 진행 중. 목표: ${fib_618:,.0f} (61.8%)"
        else:
            current_wave = 'C_ending'
            desc = f"Wave C 막바지. 반등 임박. 현재 ${current_price:,.0f}"
        
        return WaveInterpretation(
            scenario_id='zigzag_abc',
            scenario_name='Zigzag ABC (조정)',
            description=desc,
            wave_labels=labels,
            current_wave=current_wave,
            current_sub_wave='',
            projected_path=[
                {'date': current_date.isoformat(), 'price': current_price, 'label': '현재'},
                {'date': c_date.isoformat(), 'price': c_target, 'label': 'C'},
                {'date': (c_date + timedelta(days=60)).isoformat(), 'price': fib_382, 'label': '반등'}
            ],
            targets=[
                {'price': fib_618, 'fib': 0.618, 'desc': 'C파 목표'},
                {'price': fib_382, 'fib': 0.382, 'desc': '반등 목표'}
            ],
            invalidation_price=ath_price * 1.01,
            probability=probability,
            confidence=0.70
        )
    
    def _interpret_running_flat(
        self, pivots, current_price, current_date,
        ath_price, ath_date, probability
    ) -> WaveInterpretation:
        """Running Flat 해석: ATH = W3, 현재 W4 → W5 예상 (강세)"""
        # 기존 피벗을 W0-W3-W4로 재라벨링
        labels = []
        if len(pivots) >= 5:
            labels = [
                {'label': 'W0', 'date': pivots[0]['date'], 'price': pivots[0]['price']},
                {'label': 'W1', 'date': pivots[1]['date'], 'price': pivots[1]['price']},
                {'label': 'W2', 'date': pivots[2]['date'], 'price': pivots[2]['price']},
                {'label': 'W3', 'date': pivots[3]['date'], 'price': pivots[3]['price']},  # 기존 W3
                {'label': 'W4', 'date': pivots[4]['date'], 'price': pivots[4]['price']},  # 기존 W4
                # W5(ATH)는 W3 (확장)
            ]
            # ATH를 W3로 재해석
            labels[3] = {'label': 'W3 (확장)', 'date': ath_date.isoformat() if isinstance(ath_date, datetime) else ath_date, 'price': ath_price}
            labels.append({'label': 'W4 (진행중)', 'date': current_date.isoformat(), 'price': current_price})
        
        # W5 목표: ATH * 1.5 ~ 2.0
        w5_target = ath_price * 1.5
        w5_date = current_date + timedelta(days=300)
        
        return WaveInterpretation(
            scenario_id='running_flat',
            scenario_name='Running Flat (강세확산)',
            description=f"W3 고점 ${ath_price:,.0f}에서 조정 후 W5 ${w5_target:,.0f} 예상",
            wave_labels=labels,
            current_wave='W4',
            current_sub_wave='c',
            projected_path=[
                {'date': current_date.isoformat(), 'price': current_price, 'label': 'W4 저점'},
                {'date': w5_date.isoformat(), 'price': w5_target, 'label': 'W5'}
            ],
            targets=[
                {'price': w5_target, 'fib': 1.618, 'desc': 'W5 목표 (1.618x)'},
                {'price': ath_price * 2.0, 'fib': 2.0, 'desc': 'W5 확장 목표'}
            ],
            invalidation_price=pivots[0]['price'],  # W0 이탈시 무효
            probability=probability,
            confidence=0.50
        )
    
    def _interpret_expanded_flat(
        self, pivots, current_price, current_date,
        ath_price, ath_date, fib_786, probability
    ) -> WaveInterpretation:
        """Expanded Flat: W5 완료, 확장형 B파 (ATH 터치) → 깊은 C파"""
        labels = []
        wave_names = ['W0', 'W1', 'W2', 'W3', 'W4', 'W5']
        for i, p in enumerate(pivots[:6]):
            labels.append({
                'label': wave_names[i],
                'date': p['date'],
                'price': p['price']
            })
        
        # C파 목표: 78.6% 되돌림
        c_target = fib_786
        c_date = current_date + timedelta(days=90)
        
        return WaveInterpretation(
            scenario_id='expanded_flat',
            scenario_name='Expanded Flat (확장형)',
            description=f"확장형 플랫. B파가 ATH 터치 후 C파 깊은 조정 ${c_target:,.0f} 예상",
            wave_labels=labels,
            current_wave='C',
            current_sub_wave='iii',
            projected_path=[
                {'date': ath_date.isoformat() if isinstance(ath_date, datetime) else ath_date, 'price': ath_price, 'label': 'B'},
                {'date': current_date.isoformat(), 'price': current_price, 'label': '현재'},
                {'date': c_date.isoformat(), 'price': c_target, 'label': 'C'}
            ],
            targets=[
                {'price': c_target, 'fib': 0.786, 'desc': 'C파 목표 (78.6%)'}
            ],
            invalidation_price=ath_price * 1.05,
            probability=probability,
            confidence=0.40
        )
    
    def _interpret_extended_5th(
        self, pivots, current_price, current_date,
        ath_price, ath_date, probability
    ) -> WaveInterpretation:
        """Extended 5th: W5가 확장 중, 서브파동 조정 후 더 높은 고점"""
        labels = []
        wave_names = ['W0', 'W1', 'W2', 'W3', 'W4', 'W5 (진행중)']
        for i, p in enumerate(pivots[:6]):
            labels.append({
                'label': wave_names[min(i, 5)],
                'date': p['date'],
                'price': p['price']
            })
        
        # 확장 목표
        ext_target = ath_price * 1.2
        ext_date = current_date + timedelta(days=180)
        
        return WaveInterpretation(
            scenario_id='extended_5th',
            scenario_name='Extended 5th (5파 확장)',
            description=f"W5 확장 중. 현재 서브파동 조정 후 ${ext_target:,.0f} 목표",
            wave_labels=labels,
            current_wave='W5',
            current_sub_wave='iv',
            projected_path=[
                {'date': current_date.isoformat(), 'price': current_price, 'label': 'W5.iv'},
                {'date': ext_date.isoformat(), 'price': ext_target, 'label': 'W5.v'}
            ],
            targets=[
                {'price': ext_target, 'fib': 1.2, 'desc': 'W5 확장 (+20%)'},
                {'price': ath_price * 1.5, 'fib': 1.5, 'desc': 'W5 확장 (+50%)'}
            ],
            invalidation_price=pivots[4]['price'] if len(pivots) > 4 else current_price * 0.7,
            probability=probability,
            confidence=0.35
        )
    

    def _create_new_impulse_scenario(
        self,
        waves: List[Dict],
        current_price: float,
        symbol: str,
        probability: float
    ) -> WaveScenarioLive:
        """새 상승파 (Primary Wave 1) 시나리오"""
        wave_map = {w['label']: w for w in waves}
        w5 = wave_map.get('5', {})
        w0 = wave_map.get('0', {})
        
        w5_price = w5.get('price', current_price * 1.5)
        w0_price = w0.get('price', current_price * 0.3)
        
        # 새 상승파 목표: 이전 하락폭의 61.8% ~ 100% 되돌림
        decline = w5_price - current_price
        target_618 = current_price + (decline * 0.618)
        target_100 = current_price + decline
        
        return WaveScenarioLive(
            id=f"{symbol}_new_impulse",
            name="New Primary Wave 1",
            description=f"ABC 조정 완료 후 새로운 상승파 시작. 현재 ${current_price:,.0f}에서 반등하여 새 사이클의 Wave 1 형성 중.",
            wave_type=WaveType.IMPULSE,
            current_position=WavePosition.WAVE_1,
            waves=waves,
            probability=probability,
            confidence=0.5,
            invalidation_rules=[
                InvalidationRule(
                    condition_type='price_below',
                    threshold=w0_price,
                    description=f"사이클 저점 (${w0_price:,.0f}) 이탈시 무효"
                )
            ],
            targets=[
                TargetLevel(target_618, 0.4, 0.618, "61.8% 되돌림"),
                TargetLevel(target_100, 0.3, 1.0, "100% 되돌림"),
            ],
            stop_loss=current_price * 0.85,
            created_at=datetime.now().isoformat()
        )
    
    def _create_correction_scenario(
        self,
        waves: List[Dict],
        current_price: float,
        symbol: str,
        probability: float = 0.45,
        abc_position: str = 'C_wave'
    ) -> WaveScenarioLive:
        """ABC 조정 시나리오"""
        wave_map = {w['label']: w for w in waves}
        w5 = wave_map.get('5', {})
        w4 = wave_map.get('4', {})
        w0 = wave_map.get('0', {})
        
        w5_price = w5.get('price', current_price)
        w4_price = w4.get('price', current_price * 0.8)
        w0_price = w0.get('price', current_price * 0.5)
        
        # 조정 목표: 0.382 ~ 0.618 되돌림
        wave_length = w5_price - w0_price
        target_382 = w5_price - (wave_length * 0.382)
        target_618 = w5_price - (wave_length * 0.618)
        
        # B파 고점 추정 (현재가가 반등 중이면)
        # B파는 보통 A파 61.8%~100% 되돌림
        a_wave_low = w5_price - (wave_length * 0.382)  # A파 저점 추정
        b_wave_high = w5_price * 0.95  # B파 고점 (ATH의 95% 근처)
        
        # ABC 위치에 따른 설명 동적 생성
        position_desc = {
            'A_wave': 'Wave A 하락 진행 중. 반등 후 Wave B, C 예상.',
            'B_wave': 'Wave B 반등 구간. 이후 Wave C 하락 예상.',
            'C_wave': 'Wave C 하락 진행 중. 피보나치 지지선에서 반등 가능.',
            'C_ending': 'Wave C 막바지. 조정 완료 후 반등 임박.',
            'completed': 'ABC 조정 완료 추정. 새 상승파 가능성.'
        }
        
        # ABC 위치에 따른 현재 포지션
        current_pos = {
            'A_wave': WavePosition.WAVE_A,
            'B_wave': WavePosition.WAVE_B,
            'C_wave': WavePosition.WAVE_C,
            'C_ending': WavePosition.WAVE_C,
            'completed': WavePosition.WAVE_C
        }
        
        # ===== 강화된 무효화 규칙 =====
        invalidation_rules = [
            # 규칙 1: ATH 돌파 → ABC 시나리오 완전 무효
            InvalidationRule(
                condition_type='price_above',
                threshold=w5_price * 1.02,
                description=f"ATH (${w5_price:,.0f}) 2% 돌파 → ABC 무효, Extended 5th로 전환"
            ),
            # 규칙 2: B파 고점 돌파 (ABC 구조 무효화)
            InvalidationRule(
                condition_type='price_above',
                threshold=b_wave_high * 1.05,
                description=f"B파 고점 (${b_wave_high:,.0f}) 5% 돌파 → ABC 실패 가능성"
            ),
        ]
        
        # 규칙 3: W4 가격 하락 돌파 (조정이 너무 깊은 경우)
        if w4_price > w0_price:
            invalidation_rules.append(
                InvalidationRule(
                    condition_type='price_below',
                    threshold=w0_price * 0.9,
                    description=f"W0 (${w0_price:,.0f}) 10% 하향 돌파 → 구조적 붕괴"
                )
            )
        
        return WaveScenarioLive(
            id=f"{symbol}_abc_correction",
            name="ABC Correction",
            description=position_desc.get(abc_position, 'ABC 조정 진행 중'),
            wave_type=WaveType.CORRECTIVE,
            current_position=current_pos.get(abc_position, WavePosition.WAVE_C),
            waves=waves,
            probability=probability,
            confidence=0.7,
            invalidation_rules=invalidation_rules,
            targets=[
                TargetLevel(target_382, 0.5, 0.382, "38.2% 되돌림"),
                TargetLevel(target_618, 0.35, 0.618, "61.8% 되돌림"),
            ],
            stop_loss=w5_price * 1.02,
            created_at=datetime.now().isoformat()
        )
    
    def _create_new_cycle_scenario(
        self,
        waves: List[Dict],
        current_price: float,
        symbol: str,
        probability: float = 0.25,
        abc_position: str = 'C_wave'
    ) -> WaveScenarioLive:
        """새 사이클 시작 시나리오"""
        wave_map = {w['label']: w for w in waves}
        w5 = wave_map.get('5', {})
        w0 = wave_map.get('0', {})
        
        w5_price = w5.get('price', current_price)
        w0_price = w0.get('price', current_price * 0.3)
        
        # ABC 완료 여부에 따른 설명
        if abc_position in ['C_ending', 'completed']:
            desc = f"ABC 조정 완료 후 새로운 상위 사이클 시작. 현재 ${current_price:,.0f}에서 새 Supercycle Wave 1 형성 중."
        else:
            desc = "이전 5파 완료, 새로운 상위 사이클의 Wave 1 시작 예상. ABC 조정 완료 후 강한 상승 예상."
        
        return WaveScenarioLive(
            id=f"{symbol}_new_cycle",
            name="New Supercycle Wave 1",
            description=desc,
            wave_type=WaveType.IMPULSE,
            current_position=WavePosition.WAVE_1,
            waves=waves,
            probability=probability,
            confidence=0.5,
            invalidation_rules=[
                InvalidationRule(
                    condition_type='price_below',
                    threshold=w0_price,
                    description=f"사이클 시작점 (${w0_price:,.0f}) 이탈시 무효"
                )
            ],
            targets=[
                TargetLevel(w5_price * 1.5, 0.3, 1.618, "1.618x 확장 (${w5_price*1.5:,.0f})"),
                TargetLevel(w5_price * 2.0, 0.2, 2.0, "2x 확장 (${w5_price*2:,.0f})"),
            ],
            stop_loss=current_price * 0.7,
            created_at=datetime.now().isoformat()
        )
    
    def _create_extended_5th_scenario(
        self,
        waves: List[Dict],
        current_price: float,
        symbol: str,
        probability: float = 0.20
    ) -> WaveScenarioLive:
        """확장 5파 시나리오"""
        wave_map = {w['label']: w for w in waves}
        w3 = wave_map.get('3', {})
        w4 = wave_map.get('4', {})
        w5 = wave_map.get('5', {})
        
        w5_price = w5.get('price', current_price)
        w4_price = w4.get('price', current_price * 0.9)
        
        return WaveScenarioLive(
            id=f"{symbol}_extended_5th",
            name="Extended 5th Wave",
            description=f"5파가 확장 중. 현재 조정은 확장 5파 내 서브파동일 수 있음. ATH (${w5_price:,.0f}) 재돌파시 더 높은 고점 가능.",
            wave_type=WaveType.IMPULSE,
            current_position=WavePosition.WAVE_5,
            waves=waves,
            probability=probability,
            confidence=0.4,
            invalidation_rules=[
                InvalidationRule(
                    condition_type='price_below',
                    threshold=w4_price,
                    description=f"Wave 4 (${w4_price:,.0f}) 이탈시 무효"
                )
            ],
            targets=[
                TargetLevel(w5_price * 1.2, 0.4, 1.2, f"20% 추가 상승 (${w5_price*1.2:,.0f})"),
                TargetLevel(w5_price * 1.5, 0.2, 1.5, f"50% 추가 상승 (${w5_price*1.5:,.0f})"),
            ],
            stop_loss=w4_price * 0.98,
            created_at=datetime.now().isoformat()
        )
    
    def _create_wave5_scenario(
        self,
        waves: List[Dict],
        current_price: float,
        symbol: str
    ) -> WaveScenarioLive:
        """Wave 5 진행 중 시나리오"""
        wave_map = {w['label']: w for w in waves}
        w0 = wave_map.get('0', {})
        w1 = wave_map.get('1', {})
        w3 = wave_map.get('3', {})
        w4 = wave_map.get('4', {})
        
        w1_len = w1.get('price', 0) - w0.get('price', 0)
        w4_price = w4.get('price', current_price)
        
        target_equal_w1 = w4_price + w1_len
        
        return WaveScenarioLive(
            id=f"{symbol}_wave5_active",
            name="Wave 5 In Progress",
            description="Wave 5 진행 중. 목표가는 Wave 1 길이와 동일한 수준.",
            wave_type=WaveType.IMPULSE,
            current_position=WavePosition.WAVE_5,
            waves=waves,
            probability=0.70,
            confidence=0.6,
            invalidation_rules=[
                InvalidationRule(
                    condition_type='price_below',
                    threshold=w1.get('price', current_price * 0.8),
                    description="Wave 1 고점 이탈시 무효"
                )
            ],
            targets=[
                TargetLevel(target_equal_w1, 0.5, 1.0, "W5 = W1"),
                TargetLevel(w4_price + w1_len * 0.618, 0.3, 0.618, "W5 = 0.618 × W1"),
            ],
            stop_loss=w4_price * 0.95,
            created_at=datetime.now().isoformat()
        )


class WaveTracker:
    """
    통합 Elliott Wave 추적기
    
    - 초기 분석 (DualAgentExpert)
    - 다중 시나리오 생성
    - 실시간 업데이트
    - 예측 및 리포트
    - 영속 기록 저장 (NN 트레이닝용)
    - 시나리오 경로 시각화
    """
    
    def __init__(self, symbol: str, db_path: str = None):
        self.symbol = symbol
        self.dual_agent = DualAgentExpert()
        self.scenario_tree = ScenarioTree(symbol)
        self.probability_engine = ProbabilityEngine()
        self.scenario_generator = ScenarioGenerator()
        self.fib_calculator = FibonacciCalculator()
        
        # 기록 저장소
        self.db_path = db_path or f"data/wave_tracker_{symbol.replace('-', '_')}.db"
        self.history = WaveTrackerHistory(self.db_path)
        
        # Retroactive Wave System (v5.3) - 히스토리 저장 연결
        self.retroactive_adjuster = RetroactiveAdjuster(db_path=self.db_path)
        self.retro_generator = RetroScenarioGenerator(self.dual_agent)
        
        # LLM
        if LLM_AVAILABLE:
            self.llm = GeminiClient()
        else:
            self.llm = None
        
        # 상태
        self.initialized = False
        self.last_analysis = None
        self.current_state: Optional[MarketState] = None
        self.df: Optional[pd.DataFrame] = None  # 원본 데이터 저장
        
    def initialize(
        self,
        df: pd.DataFrame,
        output_dir: str = '/tmp'
    ) -> TrackingResult:
        """
        초기 분석 및 시나리오 생성
        
        Args:
            df: OHLCV 데이터
            output_dir: 차트 저장 경로
        """
        # 1. DualAgentExpert로 기본 파동 분석
        analysis = self.dual_agent.analyze(
            df=df,
            symbol=self.symbol,
            output_dir=output_dir
        )
        self.last_analysis = analysis
        
        if not analysis.final_scenario:
            return None
        
        waves = analysis.final_scenario.waves
        
        # 2. 현재 가격 (컬럼명 대소문자 유연 처리)
        close_col = 'close' if 'close' in df.columns else 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            current_price = float(df[close_col].iloc[-1].values[0])
        else:
            current_price = float(df[close_col].iloc[-1])
        
        # 3. 시나리오 생성 (DualAgentExpert 결과 그대로 사용)
        scenarios = self.scenario_generator.generate_from_analysis(
            waves=waves,
            current_price=current_price,
            symbol=self.symbol
        )
        
        for scenario in scenarios:
            self.scenario_tree.add_scenario(scenario)
        
        # 5. 현재 상태 저장
        self.current_state = MarketState(
            symbol=self.symbol,
            current_price=current_price,
            timestamp=datetime.now()
        )
        
        self.initialized = True
        
        return self.get_tracking_result()
    
    def _adjust_waves_for_ath(
        self, 
        waves: List[Dict], 
        ath_price: float, 
        ath_date,
        current_price: float
    ) -> List[Dict]:
        """
        ATH가 분석된 W5보다 높으면 파동 구조 자동 조정
        """
        wave_map = {w['label']: w for w in waves}
        w5 = wave_map.get('5')
        
        if not w5:
            return waves
        
        w5_price = w5.get('price', 0)
        
        # ATH가 W5보다 높으면 업데이트
        if ath_price > w5_price * 1.05:  # 5% 이상 차이
            # 새 W5로 ATH 설정
            new_waves = []
            for w in waves:
                if w['label'] == '5':
                    new_waves.append({
                        'label': '5',
                        'price': ath_price,
                        'date': ath_date if hasattr(ath_date, 'strftime') else str(ath_date),
                        'wave_degree': w.get('wave_degree', 'Primary'),
                        'note': 'ATH 기반 자동 조정'
                    })
                else:
                    new_waves.append(w)
            return new_waves
        
        return waves
    
    def update(self, new_price: float, timestamp: datetime = None) -> TrackingResult:
        """
        새 가격으로 상태 업데이트
        """
        if not self.initialized:
            raise ValueError("Tracker not initialized. Call initialize() first.")
        
        timestamp = timestamp or datetime.now()
        
        # 1. 무효화 체크
        invalidated = self.scenario_tree.update_with_price(new_price)
        
        # 무효화된 시나리오 기록
        for scenario_id in invalidated:
            scenario = self.scenario_tree.scenarios.get(scenario_id)
            if scenario:
                self.history.log_scenario_outcome(
                    self.symbol, scenario, new_price, 'invalidated'
                )
        
        # 2. 현재 상태 업데이트
        self.current_state = MarketState(
            symbol=self.symbol,
            current_price=new_price,
            timestamp=timestamp
        )
        
        # 3. 확률 업데이트 + 기록
        for scenario in self.scenario_tree.get_valid_scenarios():
            old_prob = scenario.probability
            
            events = self.probability_engine.detect_events(
                self.current_state, scenario
            )
            self.probability_engine.update_probability(
                scenario, self.current_state, events
            )
            
            # 확률 변화 기록
            if abs(scenario.probability - old_prob) > 0.01:
                self.history.log_probability_update(
                    self.symbol, scenario, old_prob,
                    scenario.probability, new_price, events
                )
        
        # 4. 정규화
        self.scenario_tree._normalize_probabilities()
        
        # 5. 트레이닝 피처 기록
        result = self.get_tracking_result()
        self.history.log_training_features(
            self.symbol,
            self.current_state,
            list(self.scenario_tree.scenarios.values()),
            result.primary_scenario
        )
        
        return result
    
    def get_tracking_result(self) -> TrackingResult:
        """현재 추적 결과"""
        primary = self.scenario_tree.get_primary_scenario()
        valid_scenarios = self.scenario_tree.get_valid_scenarios()
        
        # 전체 방향성
        bullish_prob = sum(
            s.probability for s in valid_scenarios
            if s.wave_type == WaveType.IMPULSE
        )
        
        if bullish_prob > 0.6:
            bias = 'bullish'
        elif bullish_prob < 0.4:
            bias = 'bearish'
        else:
            bias = 'neutral'
        
        # 주요 레벨
        key_levels = {}
        if primary:
            if primary.stop_loss:
                key_levels['stop_loss'] = primary.stop_loss
            if primary.targets:
                key_levels['target_1'] = primary.targets[0].price
            if primary.invalidation_rules:
                key_levels['invalidation'] = primary.invalidation_rules[0].threshold
        
        # 다음 예상 움직임
        next_move = self._predict_next_move(primary) if primary else "분석 필요"
        
        return TrackingResult(
            symbol=self.symbol,
            timestamp=datetime.now(),
            scenarios=list(self.scenario_tree.scenarios.values()),
            primary_scenario=primary,
            market_state=self.current_state,
            overall_bias=bias,
            confidence=primary.confidence if primary else 0,
            key_levels=key_levels,
            next_expected_move=next_move
        )
    
    def _predict_next_move(self, scenario: WaveScenarioLive) -> str:
        """다음 움직임 예측"""
        if scenario.wave_type == WaveType.CORRECTIVE:
            if scenario.current_position == WavePosition.WAVE_C:
                return f"Wave C 진행 중. 목표: ${scenario.targets[0].price:,.0f} 부근 지지 후 반등 예상."
        
        elif scenario.wave_type == WaveType.IMPULSE:
            if scenario.current_position == WavePosition.WAVE_5:
                return f"Wave 5 진행 중. 목표: ${scenario.targets[0].price:,.0f}. 이후 조정 예상."
        
        return "추가 데이터 필요"
    
    def get_report(self, use_llm: bool = True) -> str:
        """리포트 생성"""
        result = self.get_tracking_result()
        
        if use_llm and self.llm:
            return self._generate_llm_report(result)
        else:
            return result.to_report()
    
    def _generate_llm_report(self, result: TrackingResult) -> str:
        """LLM으로 자연어 리포트 생성"""
        scenario_info = "\n".join([
            f"- {s.name}: {s.probability:.0%} ({s.description})"
            for s in result.scenarios if s.is_valid
        ])
        
        prompt = f"""Create a concise Elliott Wave analysis report in Korean.

**Symbol:** {result.symbol}
**Current Price:** ${result.market_state.current_price:,.2f}
**Timestamp:** {result.timestamp.strftime('%Y-%m-%d %H:%M')}
**Overall Bias:** {result.overall_bias}

**Scenarios:**
{scenario_info}

**Key Levels:**
{json.dumps(result.key_levels, indent=2)}

Write a 2-3 paragraph analysis explaining:
1. Current wave position and what it means
2. Key levels to watch
3. Recommended action (buy/sell/wait)

Keep it concise and actionable."""

        try:
            response = self.llm.generate(
                prompt,
                model=GeminiModel.FLASH_20,
                temperature=0.3,
                max_tokens=600
            )
            return response
        except:
            return result.to_report()
    
    def get_scenario_chart(self):
        """시나리오 경로 시각화 차트 반환"""
        if not self.initialized or self.df is None:
            return None
        
        result = self.get_tracking_result()
        confirmed_waves = result.primary_scenario.waves if result.primary_scenario else []
        
        return create_scenario_path_chart(
            df=self.df,
            confirmed_waves=confirmed_waves,
            scenarios=list(self.scenario_tree.scenarios.values()),
            symbol=self.symbol
        )
    
    def get_multi_timeframe_chart(self):
        """대파동/소파동 멀티 타임프레임 차트"""
        if not self.initialized or self.df is None:
            return None
        
        result = self.get_tracking_result()
        confirmed_waves = result.primary_scenario.waves if result.primary_scenario else []
        
        return create_multi_timeframe_chart(
            df=self.df,
            confirmed_waves=confirmed_waves,
            symbol=self.symbol
        )
    
    def get_probability_history(self, scenario_id: str = None, limit: int = 100):
        """확률 변화 기록"""
        return self.history.get_probability_history(
            self.symbol, scenario_id, limit
        )
    
    def get_training_data(self):
        """NN 트레이닝용 데이터"""
        return self.history.get_training_data(self.symbol)
    
    def get_scenario_accuracy(self):
        """시나리오별 정확도 통계"""
        return self.history.get_scenario_accuracy(self.symbol)
    
    def generate_self_corrected_scenarios(
        self,
        df: pd.DataFrame = None,
        max_iterations: int = 2
    ) -> List[Dict]:
        """
        Self-Correction Loop를 적용한 4개 시나리오 생성
        
        이전 대화에서 구현된 Self-Correction 로직 통합:
        - 시간 순서 제약 적용
        - LLM을 통한 파동 수정
        - 4개 표준 시나리오 (Zigzag ABC, Running Flat, Expanded Flat, Extended 5th)
        
        Returns:
            List[Dict]: 수정된 시나리오들
        """
        if not self.initialized or not self.last_analysis:
            return []
        
        base_waves = self.last_analysis.final_scenario.waves
        
        # 현재 가격
        if df is None:
            df = self.df
        
        if isinstance(df.columns, pd.MultiIndex):
            current_price = float(df['Close'].iloc[-1].values[0])
        else:
            current_price = float(df['Close'].iloc[-1])
        
        # RetroScenarioGenerator를 통한 시나리오 생성
        scenarios = self.retro_generator.generate_scenarios(
            base_waves=base_waves,
            current_price=current_price,
            df=df
        )
        
        # 각 시나리오에 대해 Self-Correction 적용
        corrected_scenarios = []
        for scenario in scenarios:
            if self.dual_agent.available:
                result = self.dual_agent.validate_and_correct(
                    scenario_name=scenario['name'],
                    waves=scenario['waves'],
                    current_price=current_price,
                    max_iterations=max_iterations
                )
                if result.get('final_waves'):
                    scenario['waves'] = result['final_waves']
                    scenario['iterations'] = result.get('iterations', 0)
                    scenario['valid'] = result.get('valid', True)
            
            corrected_scenarios.append(scenario)
        
        return corrected_scenarios
    
    def check_retroactive_adjustment(
        self,
        auto_reanalyze: bool = True
    ) -> Optional[Dict]:
        """
        후속 파동이 이전 파동 해석과 충돌하는지 확인
        
        충돌 발생 시:
        1. 히스토리에 기록
        2. auto_reanalyze=True면 General Expert 자동 재호출
        
        Args:
            auto_reanalyze: 충돌 시 자동 재분석 여부
            
        Returns:
            충돌 정보 및 조정 제안 (없으면 None)
        """
        if not self.initialized or not self.last_analysis:
            return None
        
        base_waves = self.last_analysis.final_scenario.waves
        scenarios = list(self.scenario_tree.scenarios.values())
        current_price = self.current_state.current_price if self.current_state else 0
        
        # 충돌 체크
        conflict = self.retroactive_adjuster.check_conflict(
            scenarios=scenarios,
            current_waves=base_waves,
            current_price=current_price
        )
        
        if not conflict:
            return None
        
        # 조정 제안
        proposal = self.retroactive_adjuster.propose_adjustment(
            conflict=conflict,
            current_waves=base_waves,
            current_price=current_price
        )
        
        # 📝 히스토리 저장
        record = self.retroactive_adjuster.log_conflict(conflict, proposal, current_price)
        print(f"🚨 Conflict logged: {conflict.conflict_type.value}")
        
        result = {
            'conflict_type': conflict.conflict_type.value,
            'description': conflict.description,
            'confidence': conflict.confidence,
            'adjusted_waves': proposal.adjusted_waves,
            'reasoning': proposal.reasoning,
            'requires_general_expert': proposal.requires_general_expert,
            'logged': True,
            'reanalyzed': False
        }
        
        # 🔄 자동 재분석 (충돌 발생 시 항상)
        if auto_reanalyze and proposal.requires_general_expert and self.df is not None:
            print(f"🔄 Auto-triggering General Expert reanalysis...")
            
            # 조정된 파동 구조로 새 분석
            new_analysis = self.dual_agent.analyze(
                df=self.df,
                symbol=self.symbol,
                initial_waves=proposal.adjusted_waves,  # 조정된 파동으로 시작
                output_dir='/tmp'
            )
            
            if new_analysis and new_analysis.final_scenario:
                self.last_analysis = new_analysis
                
                # 시나리오 트리 갱신
                self.scenario_tree = ScenarioTree(self.symbol)
                new_scenarios = self.scenario_generator.generate_from_analysis(
                    waves=new_analysis.final_scenario.waves,
                    current_price=current_price,
                    symbol=self.symbol
                )
                for s in new_scenarios:
                    self.scenario_tree.add_scenario(s)
                
                result['reanalyzed'] = True
                result['new_waves'] = new_analysis.final_scenario.waves
                print(f"✅ Reanalysis complete. New scenario: {new_analysis.final_scenario.name}")
        
        return result
    
    def generate_dynamic_scenarios(
        self,
        base_waves: List[Dict] = None,
        current_price: float = None
    ) -> List[Dict]:
        """
        동적 시나리오 생성
        
        시장 상황에 따라 고정 4개가 아닌 적절한 시나리오 동적 생성:
        - ATH 근처: Extended 5th 확률 증가
        - 깊은 조정: New Cycle 시나리오 추가
        - Truncation 감지: Bearish 시나리오 추가
        """
        if base_waves is None:
            if not self.last_analysis:
                return []
            base_waves = self.last_analysis.final_scenario.waves
        
        if current_price is None:
            current_price = self.current_state.current_price if self.current_state else 0
        
        scenarios = []
        
        # 기본 4개 시나리오
        base_scenarios = self.retro_generator.generate_scenarios(
            base_waves=base_waves,
            current_price=current_price,
            df=self.df
        )
        scenarios.extend(base_scenarios)
        
        # 시장 상황 분석
        wave_map = {w.get('label'): w for w in base_waves}
        w5 = wave_map.get('5', wave_map.get('W5', {}))
        w5_price = w5.get('price', 0)
        
        # 동적 추가 시나리오
        if w5_price > 0:
            price_ratio = current_price / w5_price
            
            # ATH 근처 (95% 이상) → Super Cycle 시나리오 추가
            if price_ratio > 0.95:
                scenarios.append({
                    'name': 'Super Cycle Extension',
                    'description': 'ATH 돌파 후 슈퍼사이클 확장',
                    'waves': base_waves,
                    'probability': 0.15,
                    'pattern': 'impulse',
                    'dynamic': True
                })
            
            # 깊은 조정 (50% 이하) → New Bull Cycle 추가
            elif price_ratio < 0.5:
                scenarios.append({
                    'name': 'New Bull Cycle',
                    'description': 'ABC 완료 후 새로운 상승 사이클',
                    'waves': base_waves,
                    'probability': 0.20,
                    'pattern': 'impulse',
                    'dynamic': True
                })
        
        # 확률 정규화
        total = sum(s.get('probability', 0.25) for s in scenarios)
        if total > 0:
            for s in scenarios:
                s['probability'] = s.get('probability', 0.25) / total
        
        return scenarios
    
    def create_quadrant_chart(
        self,
        scenarios: List[Dict] = None,
        output_path: str = None
    ):
        """
        4분할 시나리오 차트 생성
        
        이전 대화의 Self-Corrected 차트 형식:
        - 2x2 그리드
        - 각 셀에 시나리오별 파동 구조
        - 현재 위치 ★ 표시
        
        Args:
            scenarios: 시나리오 리스트 (없으면 자동 생성)
            output_path: 저장 경로
            
        Returns:
            matplotlib Figure
        """
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.dates import DateFormatter
        
        if scenarios is None:
            scenarios = self.generate_self_corrected_scenarios()
        
        if not scenarios or self.df is None:
            return None
        
        # 4개로 맞추기
        while len(scenarios) < 4:
            scenarios.append(scenarios[-1].copy())
        scenarios = scenarios[:4]
        
        # 색상 팔레트
        colors = ['#EF5350', '#29B6F6', '#FFC107', '#AB47BC']  # Red, Blue, Yellow, Purple
        
        # DataFrame 준비
        df = self.df.tail(500).copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index)
        
        current_price = float(df['close'].iloc[-1])
        current_date = df.index[-1]
        
        # 4분할 차트
        fig, axes = plt.subplots(2, 2, figsize=(16, 12), facecolor='#0d1117')
        fig.suptitle(
            f'{self.symbol} Self-Corrected Elliott Wave (시간 순서 유지)',
            fontsize=16, color='white', fontweight='bold'
        )
        
        for idx, (ax, scenario, color) in enumerate(zip(axes.flat, scenarios, colors)):
            ax.set_facecolor('#161b22')
            
            # 캔들스틱 (간단 버전)
            ax.fill_between(df.index, df['low'], df['high'], alpha=0.3, color='#30363d')
            ax.plot(df.index, df['close'], color='#58a6ff', linewidth=0.8, alpha=0.7)
            
            # 파동 그리기
            waves = scenario.get('waves', [])
            if waves:
                wave_dates = []
                wave_prices = []
                wave_labels = []
                
                for w in waves:
                    try:
                        date_str = w.get('date', '')
                        if isinstance(date_str, str) and date_str:
                            if 'TBD' not in date_str:
                                wave_date = pd.to_datetime(date_str)
                                wave_dates.append(wave_date)
                                wave_prices.append(w['price'])
                                wave_labels.append(w['label'])
                    except:
                        continue
                
                if wave_dates:
                    ax.plot(wave_dates, wave_prices, color=color, linewidth=2.5, marker='o', markersize=8)
                    
                    for wd, wp, wl in zip(wave_dates, wave_prices, wave_labels):
                        ax.annotate(
                            wl, (wd, wp), 
                            textcoords="offset points", xytext=(0, 12),
                            ha='center', fontsize=9, color=color, fontweight='bold'
                        )
            
            # 현재 위치 ★
            ax.scatter([current_date], [current_price], color='#ffd700', s=200, marker='*', zorder=10)
            
            # 타이틀
            prob = scenario.get('probability', 0.25)
            ax.set_title(
                f"{scenario['name']} ({prob:.0%})",
                fontsize=13, color=color, fontweight='bold', pad=10
            )
            
            # 축 스타일
            ax.tick_params(colors='#8b949e')
            ax.xaxis.set_major_formatter(DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
            for spine in ax.spines.values():
                spine.set_color('#30363d')
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1000:.0f}k'))
            ax.grid(True, alpha=0.1, color='#30363d')
        
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        
        if output_path:
            plt.savefig(output_path, dpi=150, facecolor='#0d1117', edgecolor='none')
            print(f"📈 Chart saved: {output_path}")
        
        return fig
    
    def generate_scenario_charts(
        self,
        output_dir: str = '/tmp',
        include_projections: bool = True
    ) -> List[str]:
        """
        시나리오별 개별 차트 생성 (미래 Projection 포함)
        
        각 시나리오에 대해:
        1. 확정된 파동 구조
        2. 미래 예상 경로 (점선)
        3. 타겟/무효화 레벨
        
        Args:
            output_dir: 차트 저장 디렉토리
            include_projections: 미래 예상 경로 포함 여부
            
        Returns:
            생성된 차트 파일 경로 리스트
        """
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import timedelta
        
        if not self.initialized or self.df is None:
            print("⚠️ Tracker not initialized")
            return []
        
        # DataFrame 준비
        df = self.df.tail(500).copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index)
        
        current_price = float(df['close'].iloc[-1])
        current_date = df.index[-1]
        
        # 시나리오 가져오기
        scenarios = list(self.scenario_tree.scenarios.values())
        if not scenarios:
            print("⚠️ No scenarios available")
            return []
        
        chart_paths = []
        colors = ['#EF5350', '#29B6F6', '#66BB6A', '#FFC107', '#AB47BC']
        
        for idx, scenario in enumerate(scenarios):
            color = colors[idx % len(colors)]
            
            # Figure 생성
            fig, ax = plt.subplots(figsize=(14, 8), facecolor='#0d1117')
            ax.set_facecolor('#161b22')
            
            # 캔들스틱 그리기 (실제 OHLC 봉)
            width = 0.6  # 봉 너비 (일간 기준)
            up_color = '#26a69a'    # 양봉 (초록)
            down_color = '#ef5350'  # 음봉 (빨강)
            
            for i in range(len(df)):
                date = df.index[i]
                open_price = df['open'].iloc[i]
                high = df['high'].iloc[i]
                low = df['low'].iloc[i]
                close = df['close'].iloc[i]
                
                # 양봉/음봉 색상
                if close >= open_price:
                    body_color = up_color
                    body_bottom = open_price
                    body_height = close - open_price
                else:
                    body_color = down_color
                    body_bottom = close
                    body_height = open_price - close
                
                # 심지 (위꼬리, 아래꼬리)
                ax.plot([date, date], [low, high], color=body_color, linewidth=0.8, alpha=0.7)
                
                # 몸통 (얇은 바로 표시)
                ax.plot([date, date], [body_bottom, body_bottom + body_height], 
                       color=body_color, linewidth=2.5, solid_capstyle='butt')
            
            # 확정된 파동 그리기
            waves = getattr(scenario, 'waves', scenario.get('waves', []) if isinstance(scenario, dict) else [])
            if isinstance(waves, list) and waves:
                wave_dates = []
                wave_prices = []
                wave_labels = []
                
                for w in waves:
                    if not isinstance(w, dict):
                        continue
                    try:
                        date_str = w.get('date', '')
                        if isinstance(date_str, str) and date_str and 'TBD' not in date_str:
                            wave_date = pd.to_datetime(date_str)
                            wave_dates.append(wave_date)
                            wave_prices.append(w['price'])
                            wave_labels.append(w.get('label', ''))
                    except:
                        continue
                
                if wave_dates:
                    # 확정 파동 실선
                    ax.plot(wave_dates, wave_prices, color=color, linewidth=3, 
                           marker='o', markersize=10, label='Confirmed Waves', zorder=5)
                    
                    for wd, wp, wl in zip(wave_dates, wave_prices, wave_labels):
                        ax.annotate(
                            wl, (wd, wp),
                            textcoords="offset points", xytext=(0, 15),
                            ha='center', fontsize=11, color=color, fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='#161b22', edgecolor=color)
                        )
            
            # 미래 Projection 그리기 - 마지막 파동에서 연결
            if include_projections and wave_dates:
                targets = getattr(scenario, 'targets', [])
                
                # 마지막 확정 파동에서 시작
                last_wave_date = wave_dates[-1] if wave_dates else current_date
                last_wave_price = wave_prices[-1] if wave_prices else current_price
                
                # 연결 경로: 마지막 파동 → 현재 위치 → 타겟들
                proj_dates = [last_wave_date, current_date]
                proj_prices = [last_wave_price, current_price]
                
                # 타겟 추가
                if targets:
                    for i, target in enumerate(targets):
                        if isinstance(target, TargetLevel):
                            target_price = target.price
                        else:
                            target_price = target.get('price', current_price)
                        
                        # 타겟 도달 예상일 (45일 간격)
                        target_date = current_date + timedelta(days=45 * (i + 1))
                        proj_dates.append(target_date)
                        proj_prices.append(target_price)
                else:
                    # 타겟이 없으면 현재 시나리오 기반 예상 경로 생성 (지그재그 패턴)
                    scenario_name = getattr(scenario, 'name', '') if not isinstance(scenario, dict) else scenario.get('name', '')
                    
                    if 'correction' in scenario_name.lower() or 'abc' in scenario_name.lower():
                        # ABC 조정 시나리오: 현재 → A (하락) → B (반등) → C (급락)
                        # 중간 피벗 포함한 지그재그 패턴
                        
                        # A파: 현재 → 중간하락 → A끝
                        a_mid = current_price * 0.92
                        wave_a = current_price * 0.85
                        # B파: A끝 → 중간반등 → B끝
                        b_mid = wave_a * 1.04  
                        wave_b = current_price * 0.92
                        # C파: B끝 → 중간하락 → C끝
                        c_mid = wave_b * 0.88
                        wave_c = current_price * 0.72
                        
                        proj_dates.extend([
                            current_date + timedelta(days=15),   # A 중간
                            current_date + timedelta(days=30),   # A 끝
                            current_date + timedelta(days=45),   # B 중간
                            current_date + timedelta(days=60),   # B 끝
                            current_date + timedelta(days=75),   # C 중간
                            current_date + timedelta(days=90)    # C 끝
                        ])
                        proj_prices.extend([a_mid, wave_a, b_mid, wave_b, c_mid, wave_c])
                        
                        # 주요 라벨만 (A, B, C)
                        labels = [(30, 'A', wave_a, '#EF5350'), (60, 'B', wave_b, '#29B6F6'), (90, 'C', wave_c, '#EF5350')]
                        for days, label, price, lbl_color in labels:
                            ax.annotate(
                                label, (current_date + timedelta(days=days), price),
                                textcoords="offset points", xytext=(0, 15),
                                ha='center', fontsize=13, color=lbl_color, fontweight='bold',
                                bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor=lbl_color, alpha=0.9)
                            )
                    
                    elif 'supercycle' in scenario_name.lower() or 'new' in scenario_name.lower():
                        # 새 사이클: 현재 → 1 (상승) → 2 (조정) → 3 시작
                        # 중간 피벗 포함
                        
                        w1_mid = current_price * 1.12
                        wave_1 = current_price * 1.28  # (1) 끝
                        w2_mid = wave_1 * 0.92
                        wave_2 = current_price * 1.10  # (2) 끝 (38.2% 되돌림)
                        w3_start = wave_2 * 1.08      # (3) 시작
                        
                        proj_dates.extend([
                            current_date + timedelta(days=30),   # (1) 중간
                            current_date + timedelta(days=60),   # (1) 끝
                            current_date + timedelta(days=75),   # (2) 중간
                            current_date + timedelta(days=90),   # (2) 끝
                            current_date + timedelta(days=105)   # (3) 시작
                        ])
                        proj_prices.extend([w1_mid, wave_1, w2_mid, wave_2, w3_start])
                        
                        labels = [(60, '(1)', wave_1, '#66BB6A'), (90, '(2)', wave_2, '#FFC107'), (105, '(3)?', w3_start, '#66BB6A')]
                        for days, label, price, lbl_color in labels:
                            ax.annotate(
                                label, (current_date + timedelta(days=days), price),
                                textcoords="offset points", xytext=(0, 15),
                                ha='center', fontsize=13, color=lbl_color, fontweight='bold',
                                bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor=lbl_color, alpha=0.9)
                            )
                    
                    elif 'extended' in scenario_name.lower():
                        # 확장 5파: 현재 → 중간상승들 → 5ext 끝
                        ext_mid1 = current_price * 1.12
                        ext_mid2 = current_price * 1.08  # 소폭 조정
                        ext_mid3 = current_price * 1.22
                        ext_target = current_price * 1.35
                        
                        proj_dates.extend([
                            current_date + timedelta(days=20),
                            current_date + timedelta(days=35),
                            current_date + timedelta(days=50),
                            current_date + timedelta(days=70)
                        ])
                        proj_prices.extend([ext_mid1, ext_mid2, ext_mid3, ext_target])
                        
                        ax.annotate(
                            '5 ext', (current_date + timedelta(days=70), ext_target),
                            textcoords="offset points", xytext=(0, 15),
                            ha='center', fontsize=13, color='#AB47BC', fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor='#AB47BC', alpha=0.9)
                        )
                
                # 미래 예측 파동 시각화 (캔들 + 지그재그)
                if len(proj_dates) > 2:  # 마지막파동, 현재 + 미래 포인트들
                    future_dates = proj_dates[2:]  # 현재 이후
                    future_prices = proj_prices[2:]  # 현재 이후
                    
                    # 큰 예측 경로 라인 (굵은 지그재그)
                    ax.plot(proj_dates, proj_prices, color=color, linewidth=3.5, 
                           linestyle='-', alpha=0.6, zorder=5)
                    
                    # 각 구간에 여러 캔들로 채우기
                    from datetime import timedelta as td
                    for i, (fd, fp) in enumerate(zip(future_dates, future_prices)):
                        # 이전 가격 & 날짜
                        if i == 0:
                            prev_price = proj_prices[1]  # 현재가
                            prev_date = proj_dates[1]  # 현재날짜
                        else:
                            prev_price = future_prices[i-1]
                            prev_date = future_dates[i-1]
                        
                        # 구간을 5개 캔들로 나눔
                        days_between = (fd - prev_date).days
                        n_candles = min(5, max(3, days_between // 5))
                        
                        for j in range(n_candles):
                            # 보간 위치
                            ratio = (j + 1) / n_candles
                            candle_date = prev_date + td(days=int(days_between * ratio))
                            candle_price = prev_price + (fp - prev_price) * ratio
                            
                            # 랜덤 노이즈로 자연스러움 추가
                            import random
                            noise = 1 + random.uniform(-0.02, 0.02)
                            candle_price *= noise
                            
                            # 상승/하락 판단
                            if fp > prev_price:  # 상승 구간
                                if j % 2 == 0:  # 양봉
                                    open_p = candle_price * 0.99
                                    close_p = candle_price * 1.01
                                    high_p = close_p * 1.005
                                    low_p = open_p * 0.995
                                    c_color = '#26a69a'
                                else:  # 음봉 (조정)
                                    open_p = candle_price * 1.005
                                    close_p = candle_price * 0.995
                                    high_p = open_p * 1.005
                                    low_p = close_p * 0.995
                                    c_color = '#ef5350'
                            else:  # 하락 구간
                                if j % 2 == 0:  # 음봉
                                    open_p = candle_price * 1.01
                                    close_p = candle_price * 0.99
                                    high_p = open_p * 1.005
                                    low_p = close_p * 0.995
                                    c_color = '#ef5350'
                                else:  # 양봉 (반등)
                                    open_p = candle_price * 0.995
                                    close_p = candle_price * 1.005
                                    high_p = close_p * 1.005
                                    low_p = open_p * 0.995
                                    c_color = '#26a69a'
                            
                            # 미래 캔들 그리기 (반투명)
                            ax.plot([candle_date, candle_date], [low_p, high_p], 
                                   color=c_color, linewidth=0.8, alpha=0.4)
                            ax.plot([candle_date, candle_date], [min(open_p, close_p), max(open_p, close_p)], 
                                   color=c_color, linewidth=3, alpha=0.4, solid_capstyle='butt')
                else:
                    # 미래 포인트 없으면 기본 경로만
                    ax.plot(proj_dates, proj_prices, color=color, linewidth=2.5, 
                           linestyle='--', marker='s', markersize=8, alpha=0.7,
                           label='Projected Path', zorder=4)
                
                # 타겟 레벨 수평선
                if targets:
                    for target in targets:
                        if isinstance(target, TargetLevel):
                            t_price = target.price
                            t_prob = target.probability
                            t_desc = target.description
                        else:
                            t_price = target.get('price', 0)
                            t_prob = target.get('probability', 0.5)
                            t_desc = target.get('description', '')
                        
                        ax.axhline(y=t_price, color='#66BB6A', linestyle=':', alpha=0.5)
                        ax.annotate(
                            f'🎯 ${t_price:,.0f} ({t_prob:.0%})',
                            xy=(df.index[-1], t_price),
                            xytext=(10, 0), textcoords='offset points',
                            fontsize=9, color='#66BB6A', va='center'
                        )
                
                # 무효화 레벨
                stop_loss = getattr(scenario, 'stop_loss', None)
                if stop_loss:
                    ax.axhline(y=stop_loss, color='#EF5350', linestyle='--', alpha=0.7, linewidth=1.5)
                    ax.annotate(
                        f'🛑 SL: ${stop_loss:,.0f}',
                        xy=(df.index[-1], stop_loss),
                        xytext=(10, 0), textcoords='offset points',
                        fontsize=9, color='#EF5350', va='center'
                    )
            
            # 현재 위치 ★
            ax.scatter([current_date], [current_price], color='#ffd700', s=300, 
                      marker='*', zorder=10, label=f'Current ${current_price:,.0f}')
            
            # 타이틀 및 스타일
            if isinstance(scenario, dict):
                scenario_name = scenario.get('name', 'Unknown')
                scenario_prob = scenario.get('probability', 0.25)
                scenario_desc = scenario.get('description', '')
            else:
                scenario_name = getattr(scenario, 'name', 'Unknown')
                scenario_prob = getattr(scenario, 'probability', 0.25)
                scenario_desc = getattr(scenario, 'description', '')
            
            ax.set_title(
                f'{self.symbol} - {scenario_name} ({scenario_prob:.0%})',
                fontsize=16, color=color, fontweight='bold', pad=15
            )
            
            # 설명 박스
            ax.text(
                0.02, 0.98, scenario_desc,
                transform=ax.transAxes, fontsize=10, color='#8b949e',
                va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='#161b22', edgecolor='#30363d')
            )
            
            # 축 스타일
            ax.tick_params(colors='#8b949e')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            for spine in ax.spines.values():
                spine.set_color('#30363d')
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1000:.0f}k'))
            ax.grid(True, alpha=0.15, color='#30363d')
            ax.legend(loc='upper left', facecolor='#161b22', edgecolor='#30363d', labelcolor='#8b949e')
            
            # 저장
            safe_name = scenario_name.replace(' ', '_').replace('/', '_').lower()
            chart_path = f"{output_dir}/{self.symbol.replace('-', '_')}_{safe_name}.png"
            plt.tight_layout()
            plt.savefig(chart_path, dpi=150, facecolor='#0d1117', edgecolor='none')
            plt.close(fig)
            
            chart_paths.append(chart_path)
            print(f"📊 {scenario_name}: {chart_path}")
        
        print(f"\n✅ Generated {len(chart_paths)} scenario charts")
        return chart_paths
    
    def analyze_and_visualize(
        self,
        df: pd.DataFrame,
        output_dir: str = '/tmp'
    ) -> Dict:
        """
        분석 + 시나리오별 차트 생성 통합 플로우
        
        1. 초기 분석 (DualAgentExpert)
        2. 시나리오 생성
        3. 시나리오별 개별 차트 생성 (미래 Projection 포함)
        4. 4분할 요약 차트 생성
        
        Args:
            df: OHLCV 데이터
            output_dir: 저장 디렉토리
            
        Returns:
            분석 결과 및 차트 경로
        """
        import os
        from datetime import datetime
        
        # 데이터 캐시 경로
        cache_dir = os.path.join(output_dir, 'data_cache')
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f'{self.symbol.replace("-", "_")}_ohlcv.csv')
        
        # DataFrame 저장 (캐시)
        if df is not None:
            df.to_csv(cache_path)
            print(f"💾 Data cached: {cache_path} ({len(df)} bars)")
        else:
            # df가 None이면 캐시에서 로드 시도
            if os.path.exists(cache_path):
                df = pd.read_csv(cache_path, index_col=0)
                df.index = pd.to_datetime(df.index)  # 명시적 datetime 변환
                print(f"📂 Loaded from cache: {cache_path} ({len(df)} bars)")
            else:
                print("⚠️ No data provided and no cache found")
                return {'error': 'No data'}
        
        self.df = df  # 저장
        
        # 1. 초기화 및 분석
        print(f"\n{'='*60}")
        print(f"🎯 Elliott Wave Analysis & Visualization: {self.symbol}")
        print(f"📅 Data range: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
        print(f"{'='*60}\n")
        
        result = self.initialize(df, output_dir)
        
        if not result:
            return {'error': 'Analysis failed'}
        
        # 2. 시나리오별 개별 차트 생성
        print(f"\n📊 Generating individual scenario charts...")
        scenario_charts = self.generate_scenario_charts(output_dir, include_projections=True)
        
        # 3. 4분할 요약 차트
        print(f"\n📈 Generating quadrant summary chart...")
        quadrant_path = f"{output_dir}/{self.symbol.replace('-', '_')}_quadrant_summary.png"
        self.create_quadrant_chart(output_path=quadrant_path)
        
        # 4. 결과 정리
        return {
            'analysis': result,
            'scenario_charts': scenario_charts,
            'quadrant_chart': quadrant_path,
            'scenarios': [
                {
                    'name': s.name,
                    'probability': s.probability,
                    'description': s.description,
                    'chart': scenario_charts[i] if i < len(scenario_charts) else None
                }
                for i, s in enumerate(self.scenario_tree.scenarios.values())
            ]
        }


# === 테스트 ===
if __name__ == "__main__":
    import yfinance as yf
    
    print("=== Elliott Wave Tracker Test ===\n")
    
    df = yf.download('BTC-USD', start='2022-01-01', progress=False)
    
    tracker = WaveTracker('BTC-USD')
    result = tracker.initialize(df, output_dir='/tmp')
    
    if result:
        print(result.to_report())
        print("\n" + "="*50)
        print("\nScenario Summary:")
        print(json.dumps(tracker.scenario_tree.get_summary(), indent=2))

