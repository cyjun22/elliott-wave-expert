"""
TimeframeLinker - 멀티타임프레임 파동 연계 + 제약조건 엔진
==========================================================

핵심 역할:
  Daily(대파동) ↔ 4H(중파동) ↔ 1H(소파동) 사이의 실제 구조적 제약을
  검증하고, 위반 시 시나리오 확률을 감소시키는 교차 검증 엔진.

엘리엇 파동 이론 제약 규칙:
  1. 상위 프레임 Wave 3 내부 = 하위 프레임 1-2-3-4-5 임펄스
  2. 상위 프레임 Wave 4는 하위 프레임 3파 영역을 침범하지 않음
  3. 하위 프레임 완료 패턴은 상위 프레임 전환 신호
  4. 상위 프레임 임펄스 진행 중이면 하위 프레임에서 반대방향 큰 임펄스 불가

v3.0.0 — 2026-04-09
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────

@dataclass
class WaveDegreeMapping:
    """타임프레임 ↔ 파동 Degree 매핑"""
    timeframe: str
    degree: str          # 'Cycle', 'Primary', 'Intermediate'
    parent_tf: Optional[str]
    child_tf: Optional[str]


@dataclass
class CrossFrameConstraint:
    """교차 프레임 제약 조건"""
    rule_id: str
    description: str
    parent_tf: str
    child_tf: str
    is_satisfied: bool
    severity: str         # 'critical', 'warning', 'info'
    details: str


@dataclass
class LinkResult:
    """TimeframeLinker 교차 검증 결과 (딕셔너리로도 변환 가능)"""
    consensus_phase: str
    confidence: float
    valid_links: int
    total_links: int
    violations: List[Dict]
    wave_structure: Dict       # 타임프레임별 요약
    constraints_checked: List[CrossFrameConstraint]

    def to_dict(self) -> Dict:
        return {
            'consensus_phase': self.consensus_phase,
            'confidence': self.confidence,
            'valid_links': self.valid_links,
            'total_links': self.total_links,
            'violations': self.violations,
            'wave_structure': self.wave_structure,
        }


# ─────────────────────────────────────────────────────────────
# TimeframeLinker
# ─────────────────────────────────────────────────────────────

class TimeframeLinker:
    """
    멀티타임프레임 파동 교차 검증 엔진

    Daily/4H/1H 피벗 사이 구조적 일관성을 검증하고
    위반 사항에 대해 severity + 설명을 제공.
    """

    # 타임프레임 계층
    HIERARCHY = [
        WaveDegreeMapping('1d', 'Cycle',        None, '4h'),
        WaveDegreeMapping('4h', 'Primary',      '1d', '1h'),
        WaveDegreeMapping('1h', 'Intermediate',  '4h', None),
    ]

    # Degree 표기
    DEGREE_NOTATION = {
        'Cycle':        ('I', 'II', 'III', 'IV', 'V'),
        'Primary':      ('(1)', '(2)', '(3)', '(4)', '(5)'),
        'Intermediate': ('1', '2', '3', '4', '5'),
    }

    def __init__(self):
        self._constraints: List[CrossFrameConstraint] = []

    # ─── public API ────────────────────────────────────────

    def link_timeframes(
        self,
        tf_pivots: Dict[str, List[Dict]],
        current_price: float,
    ) -> Dict:
        """
        교차 검증 실행.

        Args:
            tf_pivots: 타임프레임별 피벗 리스트
                {'1d': [{'date':..,'price':..,'type':'high'/'low'}, ...], '4h': [...], ...}
            current_price: 현재가

        Returns:
            딕셔너리 (ForecastEngine에서 바로 사용 가능):
            {
                'consensus_phase': str,
                'confidence': float,
                'valid_links': int,
                'total_links': int,
                'violations': [{'rule': ..., 'desc': ..., 'severity': ...}],
                'wave_structure': {...}
            }
        """
        self._constraints = []
        violations: List[Dict] = []

        # 각 타임프레임 파동 구조 추출
        wave_structures: Dict[str, Dict] = {}
        for tf, pivots in tf_pivots.items():
            wave_structures[tf] = self._analyze_structure(pivots, current_price, tf)

        # 인접 타임프레임 쌍에 대해 제약 검증
        tf_pairs = self._get_adjacent_pairs(list(tf_pivots.keys()))
        total_links = 0
        valid_links = 0

        for parent_tf, child_tf in tf_pairs:
            parent_struct = wave_structures.get(parent_tf)
            child_struct = wave_structures.get(child_tf)
            if not parent_struct or not child_struct:
                continue

            pair_constraints = self._check_pair_constraints(
                parent_tf, child_tf, parent_struct, child_struct, current_price
            )
            self._constraints.extend(pair_constraints)

            for c in pair_constraints:
                total_links += 1
                if c.is_satisfied:
                    valid_links += 1
                else:
                    violations.append({
                        'rule': c.rule_id,
                        'desc': c.details,
                        'severity': c.severity,
                        'parent_tf': c.parent_tf,
                        'child_tf': c.child_tf,
                    })

        # 합의 단계 결정
        consensus_phase = self._determine_consensus(wave_structures)

        # 신뢰도 계산
        if total_links > 0:
            base_confidence = valid_links / total_links
        else:
            base_confidence = 0.5

        # 심각한 위반은 신뢰도 대폭 감소
        critical_count = sum(1 for v in violations if v['severity'] == 'critical')
        confidence = max(0.1, base_confidence - critical_count * 0.2)

        result = LinkResult(
            consensus_phase=consensus_phase,
            confidence=confidence,
            valid_links=valid_links,
            total_links=total_links,
            violations=violations,
            wave_structure=wave_structures,
            constraints_checked=self._constraints,
        )
        return result.to_dict()

    # ─── 구조 분석 ─────────────────────────────────────────

    def _analyze_structure(
        self, pivots: List[Dict], current_price: float, timeframe: str
    ) -> Dict:
        """
        피벗 리스트에서 파동 구조 추출.

        Returns:
            {
              'phase': 'impulse_3' | 'correction_B' | ...,
              'direction': 'up' | 'down',
              'wave_count': int,
              'ath': float,
              'atl': float,
              'last_pivot': Dict,
              'impulse_range': (low, high),
              'w1_end': float | None,
              'w3_end': float | None,
              'w4_end': float | None,
            }
        """
        if not pivots:
            return {
                'phase': 'unknown', 'direction': 'unknown', 'wave_count': 0,
                'ath': current_price, 'atl': current_price, 'last_pivot': {},
                'impulse_range': (current_price, current_price),
                'w1_end': None, 'w3_end': None, 'w4_end': None,
            }

        ath = max(p['price'] for p in pivots)
        atl = min(p['price'] for p in pivots)

        # 파동 라벨링 (간이)
        labels = self._label_pivots(pivots)
        wave_count = len(labels)

        # 현재 단계 추정
        phase = self._estimate_phase(labels, current_price, ath, atl)

        # 방향
        if len(pivots) >= 2:
            direction = 'up' if pivots[-1]['price'] > pivots[0]['price'] else 'down'
        else:
            direction = 'unknown'

        # 주요 파동 끝값 추출
        w1_end = labels[1]['price'] if len(labels) > 1 else None
        w3_end = labels[3]['price'] if len(labels) > 3 else None
        w4_end = labels[4]['price'] if len(labels) > 4 else None

        return {
            'phase': phase,
            'direction': direction,
            'wave_count': wave_count,
            'ath': ath,
            'atl': atl,
            'last_pivot': pivots[-1] if pivots else {},
            'impulse_range': (atl, ath),
            'w1_end': w1_end,
            'w3_end': w3_end,
            'w4_end': w4_end,
        }

    def _label_pivots(self, pivots: List[Dict]) -> List[Dict]:
        """피벗에 순서 라벨 부여 (0, 1, 2, ...)"""
        labeled = []
        for i, p in enumerate(pivots):
            labeled.append({**p, 'wave_idx': i})
        return labeled

    def _estimate_phase(
        self, labels: List[Dict], current_price: float, ath: float, atl: float
    ) -> str:
        """현재 단계 추정"""
        if not labels:
            return 'unknown'

        n = len(labels)
        # 간단한 휴리스틱: 피벗 수와 현재가 위치로 판단
        range_size = ath - atl if ath > atl else 1
        position_ratio = (current_price - atl) / range_size if range_size > 0 else 0.5

        if n >= 7:
            # 5파 + 조정 가능성
            if position_ratio < 0.4:
                return 'correction_C'
            elif position_ratio < 0.6:
                return 'correction_B'
            else:
                return 'correction_A'
        elif n >= 5:
            if position_ratio > 0.8:
                return 'impulse_5'
            elif position_ratio > 0.5:
                return 'impulse_4'
            else:
                return 'impulse_3'
        elif n >= 3:
            return 'impulse_2' if position_ratio < 0.5 else 'impulse_3'
        else:
            return 'impulse_1'

    # ─── 제약 검증 ─────────────────────────────────────────

    def _get_adjacent_pairs(self, timeframes: List[str]) -> List[Tuple[str, str]]:
        """인접 타임프레임 쌍 생성"""
        order = ['1d', '4h', '1h']
        available = [tf for tf in order if tf in timeframes]
        pairs = []
        for i in range(len(available) - 1):
            pairs.append((available[i], available[i + 1]))
        return pairs

    def _check_pair_constraints(
        self,
        parent_tf: str,
        child_tf: str,
        parent_struct: Dict,
        child_struct: Dict,
        current_price: float,
    ) -> List[CrossFrameConstraint]:
        """
        부모-자식 타임프레임 간 제약 검증.

        규칙:
          R1. 방향 일치: 상위 임펄스 진행 중이면 하위도 같은 방향
          R2. 범위 포함: 하위 프레임 가격 범위가 상위 프레임 파동 범위 안에 있어야 함
          R3. Wave 4 비침범: 상위 W4 종점이 W1 종점을 침범하면 안 됨
          R4. 하위 완료 → 상위 전환: 하위에서 5파 완료 감지 → 상위 다음 파동 예고
          R5. 비율 일관성: 하위 파동의 가격 범위가 상위 파동의 서브범위와 일관
        """
        constraints: List[CrossFrameConstraint] = []

        # R1: 방향 일치
        direction_match = (
            parent_struct['direction'] == child_struct['direction']
            or parent_struct['direction'] == 'unknown'
            or child_struct['direction'] == 'unknown'
        )
        constraints.append(CrossFrameConstraint(
            rule_id='R1_direction',
            description='상위/하위 프레임 방향 일치 검증',
            parent_tf=parent_tf,
            child_tf=child_tf,
            is_satisfied=direction_match,
            severity='warning' if not direction_match else 'info',
            details=(
                f"{parent_tf} 방향={parent_struct['direction']}, "
                f"{child_tf} 방향={child_struct['direction']}"
                + ("" if direction_match else " → 방향 불일치!")
            ),
        ))

        # R2: 범위 포함
        parent_low, parent_high = parent_struct['impulse_range']
        child_low, child_high = child_struct['impulse_range']

        # 하위 범위가 상위 범위의 150% 이내면 OK (약간의 여유)
        parent_range = parent_high - parent_low if parent_high > parent_low else 1
        range_ok = (child_high <= parent_high * 1.05) and (child_low >= parent_low * 0.95)

        constraints.append(CrossFrameConstraint(
            rule_id='R2_range_containment',
            description='하위 프레임 가격 범위가 상위 프레임 범위 내 확인',
            parent_tf=parent_tf,
            child_tf=child_tf,
            is_satisfied=range_ok,
            severity='info',
            details=(
                f"{parent_tf} 범위=[${parent_low:,.0f}~${parent_high:,.0f}], "
                f"{child_tf} 범위=[${child_low:,.0f}~${child_high:,.0f}]"
            ),
        ))

        # R3: Wave 4 비침범 (상위 프레임)
        w1_end = parent_struct.get('w1_end')
        w4_end = parent_struct.get('w4_end')
        if w1_end is not None and w4_end is not None:
            # 상승 임펄스: W4 저점이 W1 고점 아래로 내려가면 안 됨
            if parent_struct['direction'] == 'up':
                w4_ok = w4_end >= w1_end
            else:
                w4_ok = w4_end <= w1_end

            constraints.append(CrossFrameConstraint(
                rule_id='R3_wave4_overlap',
                description='Wave 4가 Wave 1 영역을 침범하지 않는지 확인',
                parent_tf=parent_tf,
                child_tf=child_tf,
                is_satisfied=w4_ok,
                severity='critical' if not w4_ok else 'info',
                details=(
                    f"{parent_tf} W1=${w1_end:,.0f}, W4=${w4_end:,.0f}"
                    + ("" if w4_ok else " → W4가 W1 영역 침범! 임펄스 구조 위반")
                ),
            ))

        # R4: 하위 완료 → 상위 전환 신호
        child_phase = child_struct.get('phase', '')
        parent_phase = parent_struct.get('phase', '')
        if 'impulse_5' in child_phase or child_phase == 'impulse_complete':
            # 하위에서 5파 완료 → 상위에서도 다음 단계로 이동 예상
            transition_expected = ('correction' in parent_phase or
                                   parent_phase in ('impulse_4', 'impulse_5'))
            constraints.append(CrossFrameConstraint(
                rule_id='R4_completion_signal',
                description='하위 프레임 5파 완료 → 상위 프레임 전환 확인',
                parent_tf=parent_tf,
                child_tf=child_tf,
                is_satisfied=True,  # 신호 자체는 항상 유효, 확인용
                severity='info',
                details=(
                    f"{child_tf}에서 5파 완료 감지 → "
                    f"{parent_tf} 현재 {parent_phase}"
                    + (" (전환 예상)" if transition_expected else " (전환 미확인)")
                ),
            ))

        # R5: 비율 일관성 (하위 변동폭 / 상위 변동폭)
        child_range = child_high - child_low if child_high > child_low else 0
        if parent_range > 0 and child_range > 0:
            ratio = child_range / parent_range
            # 하위 범위가 상위의 5%~100% 사이면 정상
            ratio_ok = 0.05 <= ratio <= 1.0
            constraints.append(CrossFrameConstraint(
                rule_id='R5_range_ratio',
                description='하위/상위 프레임 가격 범위 비율 검증',
                parent_tf=parent_tf,
                child_tf=child_tf,
                is_satisfied=ratio_ok,
                severity='warning' if not ratio_ok else 'info',
                details=(
                    f"범위 비율: {ratio:.2f} "
                    f"({child_tf}/${child_range:,.0f} / {parent_tf}/${parent_range:,.0f})"
                    + ("" if ratio_ok else " → 비정상 범위 비율")
                ),
            ))

        return constraints

    # ─── 합의 도출 ─────────────────────────────────────────

    def _determine_consensus(self, wave_structures: Dict[str, Dict]) -> str:
        """
        전체 타임프레임의 합의 단계.
        가장 높은 타임프레임 기준, 하위 프레임이 보조.
        """
        # 우선순위: 1d > 4h > 1h
        for tf in ['1d', '4h', '1h']:
            struct = wave_structures.get(tf)
            if struct and struct.get('phase', 'unknown') != 'unknown':
                return struct['phase']
        return 'unknown'
