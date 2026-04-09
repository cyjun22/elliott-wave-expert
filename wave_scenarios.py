"""
Wave Scenarios - 시나리오 생성 및 파동 해석
==========================================

wave_tracker.py에서 분리된 모듈:
- WaveInterpretation: 시나리오별 파동 해석 데이터클래스
- ScenarioWithInvalidation: 무효화 가격/시간 포함 시나리오 래퍼
- ScenarioGenerator: 다중 시나리오 자동 생성 엔진
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from experts.elliott.live_tracker import (
    WaveScenarioLive, WaveType, WavePosition,
    InvalidationRule, TargetLevel
)


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


@dataclass
class ScenarioWithInvalidation:
    """
    무효화 조건이 포함된 시나리오 래퍼

    각 시나리오에 명확한 무효화 가격, 방향, 유효 기간을 부여하여
    시나리오의 반증 가능성(falsifiability)을 보장
    """
    scenario: Dict                    # 원본 시나리오 데이터
    invalidation_price: float         # 이 가격 돌파 시 무효화
    invalidation_direction: str       # 'above' 또는 'below'
    valid_until: datetime             # 유효 기간 만료일
    falsifiable_condition: str        # 사람이 읽을 수 있는 무효화 조건 설명

    def is_invalidated(self, current_price: float) -> bool:
        """현재 가격 기준 무효화 여부 확인"""
        if self.invalidation_direction == 'above':
            return current_price > self.invalidation_price
        elif self.invalidation_direction == 'below':
            return current_price < self.invalidation_price
        return False

    def is_expired(self, now: datetime = None) -> bool:
        """유효 기간 만료 여부 확인"""
        if now is None:
            now = datetime.now()
        return now > self.valid_until


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
        ath_drop_ratio = decline_ratio

        if ath_drop_ratio > 0.40:  # 40%+ 하락
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

        if current_price > fib_236:
            return 'A_wave'
        elif current_price > fib_382:
            return 'A_wave'
        elif current_price > fib_500:
            return 'B_wave'
        elif current_price > fib_618:
            return 'C_wave'
        elif current_price > fib_786:
            return 'C_ending'
        else:
            return 'completed'

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

        if len(pivots) < 6:
            return interpretations

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

        # 시나리오 1: Zigzag ABC (W5 → ABC 조정)
        zigzag = self._interpret_zigzag(
            pivots, current_price, current_date,
            ath_price, ath_date, fib_382, fib_618, probs['correction']
        )
        interpretations.append(zigzag)

        # 시나리오 2: Running Flat (강세 확산)
        running = self._interpret_running_flat(
            pivots, current_price, current_date,
            ath_price, ath_date, probs['new_cycle']
        )
        interpretations.append(running)

        # 시나리오 3: Expanded Flat (확장형 플랫)
        expanded = self._interpret_expanded_flat(
            pivots, current_price, current_date,
            ath_price, ath_date, fib_786, probs.get('new_impulse', 0.15)
        )
        interpretations.append(expanded)

        # 시나리오 4: Extended 5th (5파 확장)
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
        labels = []
        wave_names = ['W0', 'W1', 'W2', 'W3', 'W4', 'W5']
        for i, p in enumerate(pivots[:6]):
            labels.append({
                'label': wave_names[i],
                'date': p['date'],
                'price': p['price']
            })

        a_date = ath_date + timedelta(days=45)
        b_date = ath_date + timedelta(days=90)
        c_target = fib_618
        c_date = current_date + timedelta(days=45)

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
        labels = []
        if len(pivots) >= 5:
            labels = [
                {'label': 'W0', 'date': pivots[0]['date'], 'price': pivots[0]['price']},
                {'label': 'W1', 'date': pivots[1]['date'], 'price': pivots[1]['price']},
                {'label': 'W2', 'date': pivots[2]['date'], 'price': pivots[2]['price']},
                {'label': 'W3', 'date': pivots[3]['date'], 'price': pivots[3]['price']},
                {'label': 'W4', 'date': pivots[4]['date'], 'price': pivots[4]['price']},
            ]
            labels[3] = {'label': 'W3 (확장)', 'date': ath_date.isoformat() if isinstance(ath_date, datetime) else ath_date, 'price': ath_price}
            labels.append({'label': 'W4 (진행중)', 'date': current_date.isoformat(), 'price': current_price})

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
            invalidation_price=pivots[0]['price'],
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

        wave_length = w5_price - w0_price
        target_382 = w5_price - (wave_length * 0.382)
        target_618 = w5_price - (wave_length * 0.618)

        a_wave_low = w5_price - (wave_length * 0.382)
        b_wave_high = w5_price * 0.95

        position_desc = {
            'A_wave': 'Wave A 하락 진행 중. 반등 후 Wave B, C 예상.',
            'B_wave': 'Wave B 반등 구간. 이후 Wave C 하락 예상.',
            'C_wave': 'Wave C 하락 진행 중. 피보나치 지지선에서 반등 가능.',
            'C_ending': 'Wave C 막바지. 조정 완료 후 반등 임박.',
            'completed': 'ABC 조정 완료 추정. 새 상승파 가능성.'
        }

        current_pos = {
            'A_wave': WavePosition.WAVE_A,
            'B_wave': WavePosition.WAVE_B,
            'C_wave': WavePosition.WAVE_C,
            'C_ending': WavePosition.WAVE_C,
            'completed': WavePosition.WAVE_C
        }

        invalidation_rules = [
            InvalidationRule(
                condition_type='price_above',
                threshold=w5_price * 1.02,
                description=f"ATH (${w5_price:,.0f}) 2% 돌파 → ABC 무효, Extended 5th로 전환"
            ),
            InvalidationRule(
                condition_type='price_above',
                threshold=b_wave_high * 1.05,
                description=f"B파 고점 (${b_wave_high:,.0f}) 5% 돌파 → ABC 실패 가능성"
            ),
        ]

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
