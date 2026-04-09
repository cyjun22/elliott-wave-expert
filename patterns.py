"""
Elliott Wave Patterns
=====================
엘리엇 파동 패턴 정의 및 인식

지원 패턴 (12종):
- 충격파: Impulse, Leading Diagonal, Ending Diagonal
- 조정파: Zigzag, Double Zigzag, Triple Zigzag,
          Flat, Expanded Flat, Running Flat,
          Triangle, Complex (WXY/WXYXZ)
- 미확정: Unknown
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Literal, Dict


class PatternType(Enum):
    """엘리엇 파동 패턴 유형"""

    # 충격파 (Motive Waves)
    IMPULSE = "impulse"
    LEADING_DIAGONAL = "leading_diagonal"
    ENDING_DIAGONAL = "ending_diagonal"

    # 조정파 (Corrective Waves)
    ZIGZAG = "zigzag"
    DOUBLE_ZIGZAG = "double_zigzag"
    TRIPLE_ZIGZAG = "triple_zigzag"
    FLAT = "flat"
    EXPANDED_FLAT = "expanded_flat"
    RUNNING_FLAT = "running_flat"
    TRIANGLE = "triangle"
    COMPLEX = "complex"  # WXY, WXYXZ

    # 미확정
    UNKNOWN = "unknown"


class WaveDirection(Enum):
    """파동 방향"""
    UP = "up"
    DOWN = "down"


class WaveDegree(Enum):
    """파동 차수 (Degree)"""
    GRAND_SUPERCYCLE = "grand_supercycle"  # (I), (II)...
    SUPERCYCLE = "supercycle"              # (I), (II)...
    CYCLE = "cycle"                         # I, II, III...
    PRIMARY = "primary"                     # 1, 2, 3...
    INTERMEDIATE = "intermediate"           # (1), (2)...
    MINOR = "minor"                         # i, ii, iii...
    MINUTE = "minute"                       # 1, 2, 3 (smaller)
    MINUETTE = "minuette"
    SUBMINUETTE = "subminuette"


@dataclass
class Pivot:
    """피벗 포인트"""
    timestamp: datetime
    price: float
    pivot_type: Literal["high", "low"]
    index: int = 0

    def __str__(self):
        return f"{self.pivot_type[0].upper()}:{self.price:,.0f} ({self.timestamp.strftime('%Y-%m-%d')})"


@dataclass
class Wave:
    """파동"""
    label: str  # "1", "2", "A", "B", "i", "ii", etc.
    start: Pivot
    end: Pivot
    direction: WaveDirection = None
    degree: WaveDegree = WaveDegree.PRIMARY
    sub_waves: Optional[List["Wave"]] = None

    def __post_init__(self):
        if self.direction is None:
            self.direction = WaveDirection.UP if self.end.price > self.start.price else WaveDirection.DOWN

    @property
    def size(self) -> float:
        """파동 크기 (절대값)"""
        return abs(self.end.price - self.start.price)

    @property
    def change_pct(self) -> float:
        """변동률 (%)"""
        return (self.end.price - self.start.price) / self.start.price * 100

    def __str__(self):
        return f"Wave {self.label}: {self.start.price:,.0f} → {self.end.price:,.0f} ({self.change_pct:+.1f}%)"


@dataclass
class PatternMatch:
    """패턴 매칭 결과"""
    pattern_type: PatternType
    waves: List[Wave]
    confidence: float  # 0.0 ~ 1.0
    violations: List[str] = field(default_factory=list)
    notes: str = ""


# ===== 피보나치 헬퍼 =====

def _retrace_ratio(wave_a: Wave, wave_b: Wave) -> float:
    """wave_b가 wave_a를 얼마나 되돌렸는지 비율 (0~∞)"""
    if wave_a.size == 0:
        return 0.0
    return wave_b.size / wave_a.size


def _in_fib_range(ratio: float, low: float, high: float) -> bool:
    """비율이 피보나치 범위 내인지 확인"""
    return low <= ratio <= high


def _waves_overlap(w_early: Wave, w_later: Wave, direction: WaveDirection) -> bool:
    """w_later가 w_early 가격 영역에 진입하는지 확인 (Wave 4/1 중첩 등)"""
    if direction == WaveDirection.UP:
        # 상승 추세: Wave 4 저점이 Wave 1 고점 아래로 침범
        return w_later.end.price < w_early.end.price
    else:
        # 하락 추세: Wave 4 고점이 Wave 1 저점 위로 침범
        return w_later.end.price > w_early.end.price


def _progressive_narrowing(waves: List[Wave]) -> bool:
    """파동 크기가 점진적으로 줄어드는지 (대각선 패턴)"""
    sizes = [w.size for w in waves if w.size > 0]
    if len(sizes) < 3:
        return False
    # 홀수 인덱스 파동(1,3,5)만 비교
    odd_sizes = sizes[0::2]  # 0-indexed → wave 1, 3, 5
    return all(odd_sizes[i] > odd_sizes[i + 1] for i in range(len(odd_sizes) - 1))


class PatternRecognizer:
    """
    패턴 인식기

    피벗 포인트로부터 가능한 패턴을 인식하고 확률순으로 반환
    모든 12개 PatternType을 지원
    """

    def recognize(
        self,
        pivots: List[Pivot],
        direction: WaveDirection = WaveDirection.UP
    ) -> List[PatternMatch]:
        """
        가능한 모든 패턴 매칭 (확률순 정렬)

        Args:
            pivots: 피벗 포인트 목록
            direction: 주요 추세 방향

        Returns:
            PatternMatch 목록 (신뢰도 내림차순)
        """
        results = []

        checkers = [
            self._check_impulse,
            self._check_leading_diagonal,
            self._check_ending_diagonal,
            self._check_zigzag,
            self._check_double_zigzag,
            self._check_triple_zigzag,
            self._check_flat,
            self._check_expanded_flat,
            self._check_running_flat,
            self._check_triangle,
            self._check_complex,
        ]

        for checker in checkers:
            result = checker(pivots, direction)
            if result:
                results.append(result)

        # 매칭 없으면 UNKNOWN 반환
        if not results:
            results.append(self._check_unknown(pivots, direction))

        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    # ===== 충격파 패턴 =====

    def _check_impulse(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """충격파 (5파) 패턴 체크"""
        if len(pivots) < 6:
            return None

        # 피벗에서 파동 생성 (1-indexed: Wave 1 through Wave 5)
        waves = []
        labels = ["1", "2", "3", "4", "5"]

        for i in range(min(6, len(pivots))):
            if i == 0:
                continue
            waves.append(Wave(
                label=labels[i - 1],
                start=pivots[i-1],
                end=pivots[i]
            ))

        if len(waves) < 5:
            return None

        # 규칙 검증
        violations = []
        confidence = 1.0

        # Rule 1: Wave 2 never retraces more than 100% of Wave 1
        w1, w2 = waves[0], waves[1]
        if direction == WaveDirection.UP:
            if w2.end.price < w1.start.price:
                violations.append("Wave 2 below Wave 1 start")
                confidence -= 0.4
        else:
            if w2.end.price > w1.start.price:
                violations.append("Wave 2 above Wave 1 start")
                confidence -= 0.4

        # Rule 2: Wave 3 is never the shortest
        w1_size, w3_size, w5_size = waves[0].size, waves[2].size, waves[4].size
        if w3_size < w1_size and w3_size < w5_size:
            violations.append("Wave 3 is shortest")
            confidence -= 0.5

        # Rule 3: Wave 4 never overlaps Wave 1 territory
        w1_end, w4_end = waves[0].end, waves[3].end
        if direction == WaveDirection.UP:
            if w4_end.price < w1_end.price:
                violations.append("Wave 4 overlaps Wave 1")
                confidence -= 0.3
        else:
            if w4_end.price > w1_end.price:
                violations.append("Wave 4 overlaps Wave 1")
                confidence -= 0.3

        confidence = max(0.0, confidence)

        return PatternMatch(
            pattern_type=PatternType.IMPULSE,
            waves=waves,
            confidence=confidence,
            violations=violations
        )

    def _check_leading_diagonal(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        선행 대각선 (Leading Diagonal) 패턴 체크

        - Wave 1 또는 Wave A 위치에 출현
        - 5파 구조, 모든 파동이 중첩
        - Wave 4가 Wave 1 영역 침범 (impulse와 차이점)
        - 점진적 축소 (wave 5 < wave 3 < wave 1)
        """
        if len(pivots) < 6:
            return None

        waves = []
        labels = ["1", "2", "3", "4", "5"]
        for i in range(1, min(6, len(pivots))):
            waves.append(Wave(label=labels[i - 1], start=pivots[i - 1], end=pivots[i]))

        if len(waves) < 5:
            return None

        violations = []
        confidence = 0.65

        w1, w2, w3, w4, w5 = waves[0], waves[1], waves[2], waves[3], waves[4]

        # 핵심: Wave 4가 Wave 1 영역 침범 (대각선의 특징)
        if _waves_overlap(w1, w4, direction):
            confidence += 0.10  # 대각선 특성 확인
        else:
            violations.append("Wave 4 does not overlap Wave 1 (diagonal requires overlap)")
            confidence -= 0.15

        # Wave 2가 Wave 1을 100% 이상 되돌리면 안됨
        if direction == WaveDirection.UP:
            if w2.end.price < w1.start.price:
                violations.append("Wave 2 below Wave 1 start")
                confidence -= 0.30
        else:
            if w2.end.price > w1.start.price:
                violations.append("Wave 2 above Wave 1 start")
                confidence -= 0.30

        # 점진적 축소: wave 1 > wave 3 > wave 5
        if _progressive_narrowing(waves):
            confidence += 0.10
        else:
            violations.append("Waves not progressively narrowing")
            confidence -= 0.05

        # Wave 3은 가장 짧으면 안됨
        if w3.size < w1.size and w3.size < w5.size:
            violations.append("Wave 3 is shortest (invalid even in diagonal)")
            confidence -= 0.20

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.30:
            return None

        return PatternMatch(
            pattern_type=PatternType.LEADING_DIAGONAL,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes="선행 대각선: Wave 1/A 위치, 수렴형 5파 구조"
        )

    def _check_ending_diagonal(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        종결 대각선 (Ending Diagonal) 패턴 체크

        - Wave 5 또는 Wave C 위치에 출현
        - 5파 구조, 모든 파동이 중첩
        - Wave 4가 Wave 1 영역 침범
        - 점진적 축소 또는 확장 가능
        - 완성 후 급격한 반전 예상
        """
        if len(pivots) < 6:
            return None

        waves = []
        labels = ["1", "2", "3", "4", "5"]
        for i in range(1, min(6, len(pivots))):
            waves.append(Wave(label=labels[i - 1], start=pivots[i - 1], end=pivots[i]))

        if len(waves) < 5:
            return None

        violations = []
        confidence = 0.70

        w1, w2, w3, w4, w5 = waves[0], waves[1], waves[2], waves[3], waves[4]

        # 핵심: Wave 4가 Wave 1 영역 침범
        if _waves_overlap(w1, w4, direction):
            confidence += 0.10
        else:
            violations.append("Wave 4 does not overlap Wave 1")
            confidence -= 0.20

        # Wave 2가 100% 이상 되돌리면 안됨
        if direction == WaveDirection.UP:
            if w2.end.price < w1.start.price:
                violations.append("Wave 2 below Wave 1 start")
                confidence -= 0.30
        else:
            if w2.end.price > w1.start.price:
                violations.append("Wave 2 above Wave 1 start")
                confidence -= 0.30

        # 수렴형 (contracting) 또는 확장형 (expanding)
        narrowing = _progressive_narrowing(waves)
        # 확장형: wave 5 > wave 3 > wave 1
        expanding = (w5.size > w3.size > w1.size)

        if narrowing:
            confidence += 0.05
            notes = "종결 대각선 (수렴형): 급반전 예상"
        elif expanding:
            confidence += 0.02
            notes = "종결 대각선 (확장형): 급반전 예상"
        else:
            violations.append("Neither contracting nor expanding diagonal")
            confidence -= 0.05
            notes = "종결 대각선: 급반전 예상"

        # Wave 5가 비교적 약한 경향 (수렴형에서)
        if narrowing and w5.size < w3.size:
            confidence += 0.05

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.30:
            return None

        return PatternMatch(
            pattern_type=PatternType.ENDING_DIAGONAL,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes=notes
        )

    # ===== 조정파 패턴 =====

    def _check_zigzag(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """지그재그 (5-3-5) 패턴 체크"""
        if len(pivots) < 4:
            return None

        # A-B-C 파동 생성
        waves = [
            Wave(label="A", start=pivots[0], end=pivots[1]),
            Wave(label="B", start=pivots[1], end=pivots[2]),
            Wave(label="C", start=pivots[2], end=pivots[3]),
        ]

        violations = []
        confidence = 0.8

        a_wave, b_wave, c_wave = waves

        # Zigzag: A와 C는 같은 방향
        if a_wave.direction != c_wave.direction:
            violations.append("A and C not same direction")
            confidence -= 0.3

        # B는 A의 38.2%~78.6% 되돌림
        b_retrace = _retrace_ratio(a_wave, b_wave)

        if _in_fib_range(b_retrace, 0.382, 0.786):
            confidence += 0.1
        else:
            violations.append(f"B retracement {b_retrace:.1%} outside 38.2-78.6%")
            confidence -= 0.1

        # C는 보통 A의 100%~161.8%
        c_extension = _retrace_ratio(a_wave, c_wave)
        if _in_fib_range(c_extension, 0.8, 1.8):
            confidence += 0.1

        confidence = max(0.0, min(1.0, confidence))

        return PatternMatch(
            pattern_type=PatternType.ZIGZAG,
            waves=waves,
            confidence=confidence,
            violations=violations
        )

    def _check_double_zigzag(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        이중 지그재그 (Double Zigzag) 패턴 체크

        - WXY 구조: Zigzag(W) - X - Zigzag(Y)
        - 7개 피벗 (W시작, W-A끝, W-B끝, W-C끝=X시작, X끝=Y시작, Y-B끝중략, Y끝)
        - X파는 W의 50-78.6% 되돌림
        - 단일 지그재그보다 깊은 조정
        """
        if len(pivots) < 8:
            return None

        # WXY: 7파동 (피벗 8개)
        waves = [
            Wave(label="W-A", start=pivots[0], end=pivots[1]),
            Wave(label="W-B", start=pivots[1], end=pivots[2]),
            Wave(label="W-C", start=pivots[2], end=pivots[3]),
            Wave(label="X", start=pivots[3], end=pivots[4]),
            Wave(label="Y-A", start=pivots[4], end=pivots[5]),
            Wave(label="Y-B", start=pivots[5], end=pivots[6]),
            Wave(label="Y-C", start=pivots[6], end=pivots[7]),
        ]

        violations = []
        confidence = 0.60

        w_a, w_b, w_c = waves[0], waves[1], waves[2]
        x_wave = waves[3]
        y_a, y_b, y_c = waves[4], waves[5], waves[6]

        # W 파동: A와 C 같은 방향 (지그재그 구조)
        if w_a.direction != w_c.direction:
            violations.append("W: A and C not same direction")
            confidence -= 0.15

        # Y 파동: A와 C 같은 방향
        if y_a.direction != y_c.direction:
            violations.append("Y: A and C not same direction")
            confidence -= 0.15

        # W와 Y 같은 방향 (둘 다 하락 또는 상승)
        if w_a.direction != y_a.direction:
            violations.append("W and Y not same direction")
            confidence -= 0.20

        # X파: W 전체(W-A start → W-C end)의 50-78.6% 되돌림
        w_total_size = abs(pivots[3].price - pivots[0].price)
        if w_total_size > 0:
            x_retrace = x_wave.size / w_total_size
            if _in_fib_range(x_retrace, 0.382, 0.886):
                confidence += 0.10
            else:
                violations.append(f"X retracement {x_retrace:.1%} outside 38.2-88.6%")
                confidence -= 0.10

        # B파 되돌림 체크 (W-B, Y-B)
        w_b_retrace = _retrace_ratio(w_a, w_b)
        if _in_fib_range(w_b_retrace, 0.30, 0.90):
            confidence += 0.05

        y_b_retrace = _retrace_ratio(y_a, y_b)
        if _in_fib_range(y_b_retrace, 0.30, 0.90):
            confidence += 0.05

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.30:
            return None

        return PatternMatch(
            pattern_type=PatternType.DOUBLE_ZIGZAG,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes="이중 지그재그 (WXY): 단일 지그재그보다 깊은 조정"
        )

    def _check_triple_zigzag(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        삼중 지그재그 (Triple Zigzag) 패턴 체크

        - WXYXZ 구조: Zigzag(W) - X1 - Zigzag(Y) - X2 - Zigzag(Z)
        - 11파 (피벗 12개)
        - 매우 깊은 조정, 희귀 패턴
        """
        if len(pivots) < 12:
            return None

        waves = [
            Wave(label="W-A", start=pivots[0], end=pivots[1]),
            Wave(label="W-B", start=pivots[1], end=pivots[2]),
            Wave(label="W-C", start=pivots[2], end=pivots[3]),
            Wave(label="X1", start=pivots[3], end=pivots[4]),
            Wave(label="Y-A", start=pivots[4], end=pivots[5]),
            Wave(label="Y-B", start=pivots[5], end=pivots[6]),
            Wave(label="Y-C", start=pivots[6], end=pivots[7]),
            Wave(label="X2", start=pivots[7], end=pivots[8]),
            Wave(label="Z-A", start=pivots[8], end=pivots[9]),
            Wave(label="Z-B", start=pivots[9], end=pivots[10]),
            Wave(label="Z-C", start=pivots[10], end=pivots[11]),
        ]

        violations = []
        confidence = 0.50  # 희귀 패턴이므로 기본 신뢰도 낮음

        # 각 지그재그 (W, Y, Z) 내부 A-C 방향 일치 체크
        zigzag_groups = [(waves[0], waves[2]), (waves[4], waves[6]), (waves[8], waves[10])]
        group_labels = ["W", "Y", "Z"]
        for (a, c), label in zip(zigzag_groups, group_labels):
            if a.direction != c.direction:
                violations.append(f"{label}: A and C not same direction")
                confidence -= 0.10

        # W, Y, Z 모두 같은 방향
        if not (waves[0].direction == waves[4].direction == waves[8].direction):
            violations.append("W, Y, Z not all same direction")
            confidence -= 0.15

        # X1, X2 는 반대 방향 (되돌림)
        x1, x2 = waves[3], waves[7]
        if x1.direction == waves[0].direction:
            violations.append("X1 same direction as W (should retrace)")
            confidence -= 0.10
        if x2.direction == waves[4].direction:
            violations.append("X2 same direction as Y (should retrace)")
            confidence -= 0.10

        # X 파동 크기: 이전 파동의 38.2~78.6% 되돌림
        w_total = abs(pivots[3].price - pivots[0].price)
        y_total = abs(pivots[7].price - pivots[4].price)

        if w_total > 0:
            x1_retrace = x1.size / w_total
            if _in_fib_range(x1_retrace, 0.30, 0.886):
                confidence += 0.05
            else:
                violations.append(f"X1 retrace {x1_retrace:.1%} outside range")

        if y_total > 0:
            x2_retrace = x2.size / y_total
            if _in_fib_range(x2_retrace, 0.30, 0.886):
                confidence += 0.05
            else:
                violations.append(f"X2 retrace {x2_retrace:.1%} outside range")

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.25:
            return None

        return PatternMatch(
            pattern_type=PatternType.TRIPLE_ZIGZAG,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes="삼중 지그재그 (WXYXZ): 매우 깊은 조정, 희귀 패턴"
        )

    def _check_flat(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """플랫 (3-3-5) 패턴 체크 — Regular Flat만"""
        if len(pivots) < 4:
            return None

        waves = [
            Wave(label="A", start=pivots[0], end=pivots[1]),
            Wave(label="B", start=pivots[1], end=pivots[2]),
            Wave(label="C", start=pivots[2], end=pivots[3]),
        ]

        violations = []
        confidence = 0.70

        a_wave, b_wave, c_wave = waves
        a_start = a_wave.start.price

        # Regular Flat: B ≈ A start (90-105%)
        b_end_ratio = b_wave.end.price / a_start if a_start > 0 else 0

        if _in_fib_range(b_end_ratio, 0.90, 1.05):
            confidence += 0.10
        elif b_end_ratio > 1.05:
            # Expanded 또는 Running → 여기서는 reject, 전용 체커에서 처리
            return None
        else:
            violations.append(f"B end ratio {b_end_ratio:.1%} below 90%")
            confidence -= 0.20

        # C파: A파의 100~138% 수준
        c_to_a = _retrace_ratio(a_wave, c_wave)
        if _in_fib_range(c_to_a, 0.80, 1.50):
            confidence += 0.05
        else:
            violations.append(f"C/A ratio {c_to_a:.1%} outside 80-150%")
            confidence -= 0.10

        confidence = max(0.0, min(1.0, confidence))

        return PatternMatch(
            pattern_type=PatternType.FLAT,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes="레귤러 플랫 (3-3-5): 횡보성 조정"
        )

    def _check_expanded_flat(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        확장형 플랫 (Expanded Flat) 패턴 체크

        - Wave B가 Wave A 시작점을 초과 (100-138% 되돌림)
        - Wave C가 Wave A 끝점을 크게 초과 (127-161.8%)
        """
        if len(pivots) < 4:
            return None

        waves = [
            Wave(label="A", start=pivots[0], end=pivots[1]),
            Wave(label="B", start=pivots[1], end=pivots[2]),
            Wave(label="C", start=pivots[2], end=pivots[3]),
        ]

        violations = []
        confidence = 0.65

        a_wave, b_wave, c_wave = waves
        a_start = a_wave.start.price

        # B파: A 시작점 초과 (>105%)
        b_end_ratio = b_wave.end.price / a_start if a_start > 0 else 0

        if b_end_ratio > 1.05:
            confidence += 0.10
            # B파가 A의 100-138% 되돌림 → 이상적
            b_retrace = _retrace_ratio(a_wave, b_wave)
            if _in_fib_range(b_retrace, 1.00, 1.382):
                confidence += 0.05
        else:
            # B가 A 시작점 미초과 → Expanded Flat 아님
            return None

        # C파: A보다 길어야 함 (127-161.8%)
        c_to_a = _retrace_ratio(a_wave, c_wave)
        if _in_fib_range(c_to_a, 1.15, 2.618):
            confidence += 0.10
        elif c_to_a > 1.0:
            confidence += 0.02
        else:
            violations.append(f"C/A ratio {c_to_a:.1%} too small for expanded flat")
            confidence -= 0.10

        # C가 A 끝점을 넘어서야 함
        if direction == WaveDirection.UP:
            if c_wave.end.price >= a_wave.end.price:
                violations.append("C does not exceed A end (upward correction)")
                confidence -= 0.10
        else:
            if c_wave.end.price <= a_wave.end.price:
                violations.append("C does not exceed A end (downward correction)")
                confidence -= 0.10

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.30:
            return None

        return PatternMatch(
            pattern_type=PatternType.EXPANDED_FLAT,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes="확장형 플랫: B파가 시작점 갱신, C파 깊은 조정"
        )

    def _check_running_flat(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        러닝 플랫 (Running Flat) 패턴 체크

        - Wave B가 Wave A 시작점을 크게 초과 (>105%)
        - Wave C가 Wave A 끝점에 미달 (<100% of A)
        - 강한 추세 지속 패턴
        """
        if len(pivots) < 4:
            return None

        waves = [
            Wave(label="A", start=pivots[0], end=pivots[1]),
            Wave(label="B", start=pivots[1], end=pivots[2]),
            Wave(label="C", start=pivots[2], end=pivots[3]),
        ]

        violations = []
        confidence = 0.55

        a_wave, b_wave, c_wave = waves
        a_start = a_wave.start.price

        # B파: A 시작점을 105% 이상 초과
        b_end_ratio = b_wave.end.price / a_start if a_start > 0 else 0

        if b_end_ratio > 1.05:
            confidence += 0.10
        else:
            return None  # Running flat 요건 미충족

        # C파: A 끝점에 미달 (C가 A보다 작음)
        c_to_a = _retrace_ratio(a_wave, c_wave)

        if c_to_a < 1.0:
            confidence += 0.10  # 핵심 조건: C < A
        else:
            violations.append(f"C/A ratio {c_to_a:.1%} >= 100% (not running)")
            confidence -= 0.15

        # Running flat에서 C는 A 끝점 근처까지도 안 감
        if direction == WaveDirection.UP:
            if c_wave.end.price > a_wave.end.price:
                confidence += 0.05  # C가 A끝 위에 머무름 (상승추세 강함)
        else:
            if c_wave.end.price < a_wave.end.price:
                confidence += 0.05

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.30:
            return None

        return PatternMatch(
            pattern_type=PatternType.RUNNING_FLAT,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes="러닝 플랫: 강한 추세 지속, C파 완만"
        )

    def _check_triangle(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        삼각형 (Triangle) 패턴 체크

        - 5파: A-B-C-D-E
        - 수렴형 경계 (contracting이 가장 일반적)
        - 각 파동은 조정파 (zigzag 또는 flat)
        - 최소 3개 파동이 트렌드라인 접촉
        """
        if len(pivots) < 6:
            return None

        waves = [
            Wave(label="A", start=pivots[0], end=pivots[1]),
            Wave(label="B", start=pivots[1], end=pivots[2]),
            Wave(label="C", start=pivots[2], end=pivots[3]),
            Wave(label="D", start=pivots[3], end=pivots[4]),
            Wave(label="E", start=pivots[4], end=pivots[5]),
        ]

        violations = []
        confidence = 0.65

        w_a, w_b, w_c, w_d, w_e = waves

        # 수렴 체크: 각 파동이 이전보다 작아짐
        sizes = [w.size for w in waves]
        contracting_count = sum(1 for i in range(len(sizes) - 1) if sizes[i] > sizes[i + 1])

        if contracting_count >= 3:
            confidence += 0.10  # 수렴형
            notes_type = "수렴형"
        elif contracting_count <= 1:
            # 확장형 삼각형도 가능하지만 희귀
            notes_type = "확장형"
            confidence -= 0.05
        else:
            notes_type = "대칭형"

        # 교대 방향: A↓ B↑ C↓ D↑ E↓ (또는 반대)
        directions_alternate = True
        for i in range(len(waves) - 1):
            if waves[i].direction == waves[i + 1].direction:
                directions_alternate = False
                break

        if directions_alternate:
            confidence += 0.10
        else:
            violations.append("Waves do not alternate direction")
            confidence -= 0.15

        # 고점/저점 수렴 체크 (상단/하단 경계)
        if direction == WaveDirection.UP:
            highs = [w.end.price for w in waves if w.direction == WaveDirection.UP]
            lows = [w.end.price for w in waves if w.direction == WaveDirection.DOWN]
        else:
            highs = [w.end.price for w in waves if w.direction == WaveDirection.DOWN]
            lows = [w.end.price for w in waves if w.direction == WaveDirection.UP]

        # 고점이 낮아지고 저점이 높아지면 수렴
        highs_descending = all(highs[i] >= highs[i + 1] for i in range(len(highs) - 1)) if len(highs) >= 2 else False
        lows_ascending = all(lows[i] <= lows[i + 1] for i in range(len(lows) - 1)) if len(lows) >= 2 else False

        if highs_descending and lows_ascending:
            confidence += 0.10  # 이상적 수렴
        elif highs_descending or lows_ascending:
            confidence += 0.03

        # Wave E는 보통 가장 작음
        if w_e.size <= min(w_a.size, w_b.size, w_c.size, w_d.size):
            confidence += 0.05

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.30:
            return None

        return PatternMatch(
            pattern_type=PatternType.TRIANGLE,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes=f"삼각형 ({notes_type}): 5파 수렴/확산 조정"
        )

    def _check_complex(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """
        복합 조정 (Complex) 패턴 체크

        - WXY 또는 WXYXZ
        - 서로 다른 조정 패턴의 조합 (지그재그+플랫, 플랫+삼각형 등)
        - X파는 조정 커넥터
        - 가장 유연한 패턴
        """
        if len(pivots) < 8:
            return None

        violations = []

        # WXY (7파, 피벗 8개) 먼저 체크
        if len(pivots) >= 8:
            waves = [
                Wave(label="W", start=pivots[0], end=pivots[1]),
                Wave(label="W2", start=pivots[1], end=pivots[2]),
                Wave(label="W3", start=pivots[2], end=pivots[3]),
                Wave(label="X", start=pivots[3], end=pivots[4]),
                Wave(label="Y", start=pivots[4], end=pivots[5]),
                Wave(label="Y2", start=pivots[5], end=pivots[6]),
                Wave(label="Y3", start=pivots[6], end=pivots[7]),
            ]
            structure = "WXY"
            confidence = 0.50
        else:
            return None

        # WXYXZ (11파, 피벗 12개) — 더 높은 우선순위
        if len(pivots) >= 12:
            waves = [
                Wave(label="W", start=pivots[0], end=pivots[1]),
                Wave(label="W2", start=pivots[1], end=pivots[2]),
                Wave(label="W3", start=pivots[2], end=pivots[3]),
                Wave(label="X1", start=pivots[3], end=pivots[4]),
                Wave(label="Y", start=pivots[4], end=pivots[5]),
                Wave(label="Y2", start=pivots[5], end=pivots[6]),
                Wave(label="Y3", start=pivots[6], end=pivots[7]),
                Wave(label="X2", start=pivots[7], end=pivots[8]),
                Wave(label="Z", start=pivots[8], end=pivots[9]),
                Wave(label="Z2", start=pivots[9], end=pivots[10]),
                Wave(label="Z3", start=pivots[10], end=pivots[11]),
            ]
            structure = "WXYXZ"
            confidence = 0.45  # 더 복잡 → 기본 신뢰도 낮음

        # X파(들)가 반대 방향인지 확인
        if structure == "WXY":
            x_wave = waves[3]
            w_dir = waves[0].direction
            if x_wave.direction == w_dir:
                violations.append("X wave same direction as W")
                confidence -= 0.10
        elif structure == "WXYXZ":
            x1_wave = waves[3]
            x2_wave = waves[7]
            w_dir = waves[0].direction
            if x1_wave.direction == w_dir:
                violations.append("X1 same direction as W")
                confidence -= 0.08
            if x2_wave.direction == waves[4].direction:
                violations.append("X2 same direction as Y")
                confidence -= 0.08

        # 전체적으로 같은 방향 진행 (W와 Y는 같은 방향)
        if structure == "WXY":
            if waves[0].direction == waves[4].direction:
                confidence += 0.08
            else:
                violations.append("W and Y not same direction")
                confidence -= 0.10
        elif structure == "WXYXZ":
            if waves[0].direction == waves[4].direction == waves[8].direction:
                confidence += 0.10
            else:
                violations.append("W, Y, Z not all same direction")
                confidence -= 0.10

        # 각 파동 그룹 내 A-C 비율 대략 체크
        # W 그룹: waves[0:3], Y 그룹: waves[4:7]
        for grp_start, grp_label in [(0, "W"), (4, "Y")]:
            if grp_start + 2 < len(waves):
                grp_a = waves[grp_start]
                grp_c = waves[grp_start + 2]
                if grp_a.direction == grp_c.direction:
                    confidence += 0.03

        confidence = max(0.0, min(1.0, confidence))

        if confidence < 0.25:
            return None

        return PatternMatch(
            pattern_type=PatternType.COMPLEX,
            waves=waves,
            confidence=confidence,
            violations=violations,
            notes=f"복합 조정 ({structure}): 다양한 조정 패턴 조합"
        )

    def _check_unknown(
        self,
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> PatternMatch:
        """
        미확정 패턴 (catch-all)

        어떤 패턴에도 매칭되지 않을 때의 기본 반환
        """
        waves = []
        for i in range(1, min(len(pivots), 6)):
            waves.append(Wave(
                label=str(i),
                start=pivots[i - 1],
                end=pivots[i]
            ))

        num_waves = len(waves)
        if num_waves == 0:
            notes = "피벗 데이터 부족"
        elif num_waves <= 2:
            notes = f"{num_waves}개 파동 감지, 패턴 확정 불가"
        else:
            up_count = sum(1 for w in waves if w.direction == WaveDirection.UP)
            down_count = num_waves - up_count
            notes = f"{num_waves}개 파동 (상승 {up_count}, 하락 {down_count}), 명확한 패턴 미발견"

        return PatternMatch(
            pattern_type=PatternType.UNKNOWN,
            waves=waves,
            confidence=0.20,
            violations=["No recognized pattern matched"],
            notes=notes
        )

    # ===== 설명 =====

    def get_pattern_description(self, pattern_type: PatternType) -> str:
        """패턴 설명 반환"""
        descriptions = {
            PatternType.IMPULSE: "충격파 (5파 구조). 추세 방향으로 진행. Wave 3이 가장 길고, Wave 4는 Wave 1 영역 미침범.",
            PatternType.LEADING_DIAGONAL: "선행 대각선 (5파 수렴). Wave 1 또는 A 위치 출현. 파동 중첩, 점진적 축소. 새 추세 시작 신호.",
            PatternType.ENDING_DIAGONAL: "종결 대각선 (5파 수렴/확장). Wave 5 또는 C 위치 출현. 완성 후 급격한 반전 예상.",
            PatternType.ZIGZAG: "지그재그 (5-3-5). 급격한 조정. B파 38.2-78.6% 되돌림, C파 ≈ A파 길이.",
            PatternType.DOUBLE_ZIGZAG: "이중 지그재그 (WXY). 단일 지그재그보다 깊은 조정. X파로 연결된 두 지그재그.",
            PatternType.TRIPLE_ZIGZAG: "삼중 지그재그 (WXYXZ). 매우 깊은 조정. 희귀 패턴. 두 X파로 연결된 세 지그재그.",
            PatternType.FLAT: "레귤러 플랫 (3-3-5). 횡보성 조정. B파가 A 시작점 근처까지 되돌림.",
            PatternType.EXPANDED_FLAT: "확장 플랫. B파가 A 시작점 초과 (100-138%), C파 깊은 조정 (127-161.8%). 강한 추세 후 출현.",
            PatternType.RUNNING_FLAT: "러닝 플랫. B파가 A 시작점 크게 초과, C파는 A 끝점 미달. 강한 추세 지속 신호.",
            PatternType.TRIANGLE: "삼각형 (A-B-C-D-E). 수렴형 조정. 5파 교대 구조. 돌파 방향으로 급격한 움직임 예상.",
            PatternType.COMPLEX: "복합 조정 (WXY 또는 WXYXZ). 다양한 조정 패턴의 조합. 가장 유연한 패턴.",
            PatternType.UNKNOWN: "미확정 패턴. 명확한 엘리엇 파동 구조가 식별되지 않음. 추가 데이터 필요.",
        }
        return descriptions.get(pattern_type, "알 수 없는 패턴")
