"""
Elliott Wave Validation
=======================
엘리엇 파동 이론 규칙 검증
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from .patterns import Wave, PatternType, WaveDirection


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool
    violations: List[str]
    warnings: List[str]
    confidence: float  # 0.0 ~ 1.0
    invalidation_level: Optional[float] = None
    notes: str = ""


class WaveValidator:
    """
    엘리엇 파동 규칙 검증기
    
    어떤 심볼/타임프레임에서도 동일한 규칙 적용
    """
    
    def validate(
        self, 
        waves: List[Wave], 
        pattern_type: PatternType
    ) -> ValidationResult:
        """
        통합 검증
        
        Args:
            waves: 파동 목록
            pattern_type: 패턴 유형
            
        Returns:
            ValidationResult
        """
        if pattern_type == PatternType.IMPULSE:
            return self._validate_impulse(waves)
        elif pattern_type in [PatternType.ZIGZAG, PatternType.DOUBLE_ZIGZAG]:
            return self._validate_zigzag(waves)
        elif pattern_type in [PatternType.FLAT, PatternType.EXPANDED_FLAT, PatternType.RUNNING_FLAT]:
            return self._validate_flat(waves, pattern_type)
        else:
            return ValidationResult(
                is_valid=True,
                violations=[],
                warnings=["Pattern validation not implemented"],
                confidence=0.5
            )
    
    def _validate_impulse(self, waves: List[Wave]) -> ValidationResult:
        """
        충격파 3대 규칙 검증
        
        1. Wave 2 never retraces more than 100% of Wave 1
        2. Wave 3 is never the shortest
        3. Wave 4 never overlaps Wave 1 price territory
        """
        violations = []
        warnings = []
        confidence = 1.0
        
        if len(waves) < 5:
            return ValidationResult(
                is_valid=False,
                violations=["Insufficient waves for impulse (need 5)"],
                warnings=[],
                confidence=0.0
            )
        
        w1, w2, w3, w4, w5 = waves[:5]
        direction = w1.direction
        
        # Rule 1: Wave 2 retrace
        if direction == WaveDirection.UP:
            if w2.end.price <= w1.start.price:
                violations.append(f"Rule 1: Wave 2 ({w2.end.price:,.0f}) below Wave 1 start ({w1.start.price:,.0f})")
                confidence -= 0.4
        else:
            if w2.end.price >= w1.start.price:
                violations.append(f"Rule 1: Wave 2 ({w2.end.price:,.0f}) above Wave 1 start ({w1.start.price:,.0f})")
                confidence -= 0.4
        
        # Rule 2: Wave 3 shortest check
        sizes = [w1.size, w3.size, w5.size]
        if w3.size == min(sizes):
            violations.append(f"Rule 2: Wave 3 ({w3.size:,.0f}) is shortest (W1:{w1.size:,.0f}, W5:{w5.size:,.0f})")
            confidence -= 0.5
        
        # Rule 3: Wave 4 overlap
        if direction == WaveDirection.UP:
            if w4.end.price < w1.end.price:
                violations.append(f"Rule 3: Wave 4 ({w4.end.price:,.0f}) overlaps Wave 1 ({w1.end.price:,.0f})")
                confidence -= 0.3
        else:
            if w4.end.price > w1.end.price:
                violations.append(f"Rule 3: Wave 4 ({w4.end.price:,.0f}) overlaps Wave 1 ({w1.end.price:,.0f})")
                confidence -= 0.3
        
        # Guidelines — apply graduated confidence penalties
        # Wave 3 is often the longest
        if w3.size < w1.size and w3.size < w5.size:
            warnings.append("Wave 3 is not longest (guideline, -5% confidence)")
            confidence -= 0.05

        # Wave 2 typically retraces 50-61.8% of Wave 1 (alternation guideline)
        w2_retrace = w2.size / w1.size if w1.size > 0 else 0
        if w2_retrace < 0.382 or w2_retrace > 0.786:
            warnings.append(f"Wave 2 retracement ({w2_retrace:.1%}) outside typical 38.2-78.6% (-10% confidence)")
            confidence -= 0.10

        # Volume guideline: Wave 3 should have stronger momentum
        # (structural check only — actual volume validation is in subwave_analyzer)
        if w3.size > 0 and w1.size > 0 and w3.size < w1.size * 0.8:
            warnings.append("Wave 3 momentum weaker than Wave 1 (-10% confidence)")
            confidence -= 0.10

        # Invalidation level: Wave 1 start
        invalidation = w1.start.price
        
        confidence = max(0.0, min(1.0, confidence))
        
        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            confidence=confidence,
            invalidation_level=invalidation
        )
    
    def _validate_zigzag(self, waves: List[Wave]) -> ValidationResult:
        """
        지그재그 규칙 검증
        
        - A: 5파 구조
        - B: 3파 구조, A의 38.2%~78.6% 되돌림
        - C: 5파 구조, 보통 A의 100%~161.8%
        """
        violations = []
        warnings = []
        confidence = 0.8
        
        if len(waves) < 3:
            return ValidationResult(
                is_valid=False,
                violations=["Insufficient waves for zigzag (need 3)"],
                warnings=[],
                confidence=0.0
            )
        
        a, b, c = waves[:3]
        a_size = a.size
        
        # B retrace check
        b_retrace = b.size / a_size if a_size > 0 else 0
        if b_retrace < 0.382:
            warnings.append(f"B retracement ({b_retrace:.1%}) below 38.2%")
            confidence -= 0.1
        elif b_retrace > 0.786:
            warnings.append(f"B retracement ({b_retrace:.1%}) above 78.6%")
            confidence -= 0.1
        
        # C extension check
        c_extension = c.size / a_size if a_size > 0 else 0
        if c_extension < 0.618:
            warnings.append(f"C extension ({c_extension:.1%}) below 61.8%")
        
        # A and C should be in same direction
        if a.direction != c.direction:
            violations.append("A and C waves in different directions")
            confidence -= 0.3
        
        # Invalidation: B cannot exceed A's start
        invalidation = a.start.price
        
        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            confidence=max(0.0, confidence),
            invalidation_level=invalidation
        )
    
    def _validate_flat(
        self, 
        waves: List[Wave],
        pattern_type: PatternType
    ) -> ValidationResult:
        """
        플랫 규칙 검증
        
        Regular Flat: B ≈ 90-105% of A's start
        Expanded Flat: B > A's start
        Running Flat: B > A's start, C > A's end
        """
        violations = []
        warnings = []
        confidence = 0.75
        
        if len(waves) < 3:
            return ValidationResult(
                is_valid=False,
                violations=["Insufficient waves for flat (need 3)"],
                warnings=[],
                confidence=0.0
            )
        
        a, b, c = waves[:3]
        a_start = a.start.price
        a_end = a.end.price
        
        # B wave relationship to A's start
        if pattern_type == PatternType.EXPANDED_FLAT:
            # B should exceed A's start
            if a.direction == WaveDirection.DOWN:
                if b.end.price <= a_start:
                    warnings.append(f"Expanded Flat: B ({b.end.price:,.0f}) should exceed A start ({a_start:,.0f})")
                    confidence -= 0.15
            else:
                if b.end.price >= a_start:
                    warnings.append(f"Expanded Flat: B ({b.end.price:,.0f}) should be below A start ({a_start:,.0f})")
                    confidence -= 0.15
        
        elif pattern_type == PatternType.RUNNING_FLAT:
            # B exceeds A start, C doesn't reach A end
            if a.direction == WaveDirection.DOWN:
                if c.end.price < a_end:
                    warnings.append("Running Flat: C should not exceed A's end")
                    confidence -= 0.1
        
        # C wave relationship
        c_extension = c.size / a.size if a.size > 0 else 0
        if c_extension < 0.618:
            warnings.append(f"C wave ({c_extension:.1%}) smaller than 61.8% of A")
        
        # Wave 4 invalidation for correction from impulse
        invalidation = None  # Will be set by caller based on context
        
        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            confidence=max(0.0, confidence),
            invalidation_level=invalidation
        )
    
    def get_invalidation_level(
        self, 
        waves: List[Wave], 
        pattern_type: PatternType,
        wave4_price: float = None
    ) -> float:
        """
        패턴별 무효화 레벨 자동 계산
        
        Args:
            waves: 파동 목록
            pattern_type: 패턴 유형
            wave4_price: (Optional) 충격파의 Wave 4 가격 (조정파 검증용)
            
        Returns:
            무효화 가격 레벨
        """
        if not waves:
            return None
        
        if pattern_type == PatternType.IMPULSE:
            # Wave 1의 시작점
            return waves[0].start.price
        
        elif pattern_type in [PatternType.ZIGZAG, PatternType.FLAT, 
                              PatternType.EXPANDED_FLAT, PatternType.RUNNING_FLAT]:
            # 조정파: Wave 4 레벨 (제공된 경우)
            if wave4_price:
                return wave4_price
            # 또는 A파 시작점
            return waves[0].start.price
        
        return None
