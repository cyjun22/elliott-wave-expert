"""
Elliott Wave Targets
====================
피보나치 기반 목표가 계산
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from .patterns import Wave, PatternType, WaveDirection


@dataclass
class TargetLevel:
    """목표가 레벨"""
    name: str
    price: float
    ratio: float
    level_type: str  # "retracement", "extension", "projection"
    is_primary: bool = False  # 주요 레벨 여부
    note: str = ""


class TargetCalculator:
    """
    피보나치 목표가 계산기
    
    어떤 파동 패턴에서도 동일한 피보나치 비율 적용
    """
    
    # 피보나치 되돌림 레벨
    RETRACEMENT_LEVELS = {
        "fib_236": 0.236,
        "fib_382": 0.382,
        "fib_500": 0.500,
        "fib_618": 0.618,
        "fib_786": 0.786,
    }
    
    # 피보나치 확장 레벨
    EXTENSION_LEVELS = {
        "ext_100": 1.000,
        "ext_1272": 1.272,
        "ext_1618": 1.618,
        "ext_200": 2.000,
        "ext_2618": 2.618,
    }
    
    def calculate_retracement(
        self, 
        start: float, 
        end: float
    ) -> Dict[str, TargetLevel]:
        """
        되돌림 레벨 계산
        
        Args:
            start: 파동 시작 가격
            end: 파동 종료 가격
            
        Returns:
            레벨별 TargetLevel
        """
        move = end - start
        direction = "up" if move > 0 else "down"
        
        targets = {}
        for name, ratio in self.RETRACEMENT_LEVELS.items():
            price = end - (move * ratio)
            is_primary = ratio in [0.382, 0.618]
            
            targets[name] = TargetLevel(
                name=name,
                price=price,
                ratio=ratio,
                level_type="retracement",
                is_primary=is_primary,
                note=f"{ratio:.1%} retracement"
            )
        
        return targets
    
    def calculate_extension(
        self, 
        wave1_start: float,
        wave1_end: float,
        wave2_end: float
    ) -> Dict[str, TargetLevel]:
        """
        확장 레벨 계산 (Wave 3, 5, C 타겟)
        
        공식: target = wave2_end + (wave1_size * ratio)
        
        Args:
            wave1_start: Wave 1 시작 가격
            wave1_end: Wave 1 종료 가격
            wave2_end: Wave 2 종료 가격
            
        Returns:
            레벨별 TargetLevel
        """
        wave1_size = abs(wave1_end - wave1_start)
        direction = 1 if wave1_end > wave1_start else -1
        
        targets = {}
        for name, ratio in self.EXTENSION_LEVELS.items():
            price = wave2_end + (wave1_size * ratio * direction)
            is_primary = ratio in [1.0, 1.618]
            
            targets[name] = TargetLevel(
                name=name,
                price=price,
                ratio=ratio,
                level_type="extension",
                is_primary=is_primary,
                note=f"{ratio:.1%} extension of Wave 1"
            )
        
        return targets
    
    def calculate_impulse_targets(
        self, 
        waves: List[Wave]
    ) -> Dict[str, Dict]:
        """
        충격파 각 파동별 목표가
        
        Returns:
            {
                "wave3": {...targets...},
                "wave5": {...targets...},
                "correction": {...targets...}  # 조정 예상
            }
        """
        result = {}
        
        if len(waves) < 2:
            return result
        
        # Wave 3 targets (from Wave 1)
        if len(waves) >= 2:
            w1, w2 = waves[0], waves[1]
            result["wave3"] = self.calculate_extension(
                w1.start.price, w1.end.price, w2.end.price
            )
        
        # Wave 5 targets (from Wave 1 or Wave 3)
        if len(waves) >= 4:
            w1, w4 = waves[0], waves[3]
            # Wave 5 typically 61.8-100% of Wave 1
            result["wave5"] = self.calculate_extension(
                w1.start.price, w1.end.price, w4.end.price
            )
        
        # Correction targets (after Wave 5)
        if len(waves) >= 5:
            w5 = waves[4]
            impulse_start = waves[0].start.price
            impulse_end = w5.end.price
            result["correction"] = self.calculate_retracement(
                impulse_start, impulse_end
            )
        
        return result
    
    def calculate_correction_targets(
        self, 
        waves: List[Wave],
        pattern_type: PatternType = PatternType.ZIGZAG,
        wave4_price: float = None
    ) -> Dict[str, TargetLevel]:
        """
        조정파 목표가 계산
        
        Args:
            waves: A, B, (C) 파동
            pattern_type: 조정 패턴 유형
            wave4_price: 충격파 Wave 4 가격 (무효화 레벨)
        """
        targets = {}
        
        if len(waves) < 2:
            return targets
        
        a_wave, b_wave = waves[0], waves[1]
        a_size = a_wave.size
        
        # C wave targets = extension from A
        # 공식: C = B + (A size * ratio) in A's direction
        direction = -1 if a_wave.direction == WaveDirection.DOWN else 1
        
        for ratio in [1.0, 1.272, 1.618]:
            c_target = b_wave.end.price + (a_size * ratio * direction * -1)
            name = f"c_{int(ratio*100)}"
            
            note = ""
            if wave4_price and c_target < wave4_price:
                note = f"⚠️ Below Wave 4 (${wave4_price:,.0f})"
            
            targets[name] = TargetLevel(
                name=name,
                price=c_target,
                ratio=ratio,
                level_type="extension",
                is_primary=(ratio == 1.0 or ratio == 1.618),
                note=note
            )
        
        # A = C target (common)
        targets["c_equals_a"] = TargetLevel(
            name="c_equals_a",
            price=a_wave.end.price,
            ratio=1.0,
            level_type="projection",
            is_primary=True,
            note="C = A (equal length)"
        )
        
        # Wave 4 support (if provided)
        if wave4_price:
            targets["wave4_support"] = TargetLevel(
                name="wave4_support",
                price=wave4_price,
                ratio=0,
                level_type="invalidation",
                is_primary=True,
                note="Pattern invalidation if broken"
            )
        
        return targets
    
    def get_immediate_targets(
        self, 
        current_price: float,
        all_targets: Dict[str, TargetLevel],
        direction: str = "down"  # "up" or "down"
    ) -> List[TargetLevel]:
        """
        현재가 기준 즉각 타겟 반환
        
        Args:
            current_price: 현재 가격
            all_targets: 모든 목표가
            direction: 예상 방향
            
        Returns:
            가장 가까운 순서대로 정렬된 타겟 목록
        """
        immediate = []
        
        for target in all_targets.values():
            if direction == "down" and target.price < current_price:
                immediate.append(target)
            elif direction == "up" and target.price > current_price:
                immediate.append(target)
        
        # 거리순 정렬
        immediate.sort(
            key=lambda t: abs(t.price - current_price)
        )
        
        return immediate
