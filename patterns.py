"""
Elliott Wave Patterns
=====================
엘리엇 파동 패턴 정의 및 인식
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


class PatternRecognizer:
    """
    패턴 인식기
    
    피벗 포인트로부터 가능한 패턴을 인식하고 확률순으로 반환
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
        matches = []
        
        # 충격파 체크 (5파)
        if len(pivots) >= 6:  # 0-1-2-3-4-5
            impulse = self._check_impulse(pivots, direction)
            if impulse:
                matches.append(impulse)
        
        # 지그재그 체크 (ABC)
        if len(pivots) >= 4:
            zigzag = self._check_zigzag(pivots, direction)
            if zigzag:
                matches.append(zigzag)
        
        # 플랫 체크 (ABC)
        if len(pivots) >= 4:
            flat = self._check_flat(pivots, direction)
            if flat:
                matches.append(flat)
        
        # 신뢰도 정렬
        matches.sort(key=lambda x: x.confidence, reverse=True)
        
        return matches
    
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
        a_size = a_wave.size
        b_retrace = b_wave.size / a_size if a_size > 0 else 0
        
        if 0.382 <= b_retrace <= 0.786:
            confidence += 0.1
        else:
            violations.append(f"B retracement {b_retrace:.1%} outside 38.2-78.6%")
            confidence -= 0.1
        
        # C는 보통 A의 100%~161.8%
        c_extension = c_wave.size / a_size if a_size > 0 else 0
        if 0.8 <= c_extension <= 1.8:
            confidence += 0.1
        
        confidence = max(0.0, min(1.0, confidence))
        
        return PatternMatch(
            pattern_type=PatternType.ZIGZAG,
            waves=waves,
            confidence=confidence,
            violations=violations
        )
    
    def _check_flat(
        self, 
        pivots: List[Pivot],
        direction: WaveDirection
    ) -> Optional[PatternMatch]:
        """플랫 (3-3-5) 패턴 체크"""
        if len(pivots) < 4:
            return None
        
        waves = [
            Wave(label="A", start=pivots[0], end=pivots[1]),
            Wave(label="B", start=pivots[1], end=pivots[2]),
            Wave(label="C", start=pivots[2], end=pivots[3]),
        ]
        
        violations = []
        confidence = 0.7
        
        a_wave, b_wave, c_wave = waves
        a_start = a_wave.start.price
        
        # Regular Flat: B ≈ A start (90-105%)
        b_retrace = b_wave.end.price / a_start if a_start > 0 else 0
        
        if 0.90 <= b_retrace <= 1.05:
            pattern_type = PatternType.FLAT
            confidence += 0.1
        elif b_retrace > 1.05:
            # Expanded Flat: B > A start
            pattern_type = PatternType.EXPANDED_FLAT
            confidence += 0.15
            
            # Running Flat: C doesn't reach A end
            if direction == WaveDirection.UP:
                if c_wave.end.price > a_wave.end.price:
                    pattern_type = PatternType.RUNNING_FLAT
        else:
            violations.append(f"B retrace {b_retrace:.1%} below 90%")
            pattern_type = PatternType.FLAT
            confidence -= 0.2
        
        confidence = max(0.0, min(1.0, confidence))
        
        return PatternMatch(
            pattern_type=pattern_type,
            waves=waves,
            confidence=confidence,
            violations=violations
        )
    
    def get_pattern_description(self, pattern_type: PatternType) -> str:
        """패턴 설명 반환"""
        descriptions = {
            PatternType.IMPULSE: "충격파 (5파 구조). 추세 방향으로 진행.",
            PatternType.ZIGZAG: "지그재그 (5-3-5). 급격한 조정.",
            PatternType.FLAT: "플랫 (3-3-5). 횡보성 조정.",
            PatternType.EXPANDED_FLAT: "확장 플랫. B파가 시작점 갱신.",
            PatternType.RUNNING_FLAT: "러닝 플랫. C파가 완만.",
            PatternType.TRIANGLE: "삼각형 (3-3-3-3-3). 수렴형 조정.",
        }
        return descriptions.get(pattern_type, "알 수 없는 패턴")
