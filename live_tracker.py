"""
Elliott Wave Live Tracker - 실시간 다중 시나리오 추적 시스템
============================================================
- 다중 시나리오 동시 추적
- 베이지안 확률 업데이트
- 무효화 조건 자동 감지
- Cascading 예측
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from enum import Enum
import json


class WaveType(Enum):
    """파동 유형"""
    IMPULSE = "impulse"        # 충격파 1-2-3-4-5
    CORRECTIVE = "corrective"  # 조정파 A-B-C
    TRIANGLE = "triangle"      # 삼각형 A-B-C-D-E
    DIAGONAL = "diagonal"      # 대각선
    UNKNOWN = "unknown"


class WavePosition(Enum):
    """현재 파동 위치"""
    WAVE_1 = "wave_1"
    WAVE_2 = "wave_2"
    WAVE_3 = "wave_3"
    WAVE_4 = "wave_4"
    WAVE_5 = "wave_5"
    WAVE_A = "wave_a"
    WAVE_B = "wave_b"
    WAVE_C = "wave_c"
    COMPLETE = "complete"


@dataclass
class PriceLevel:
    """가격 레벨"""
    price: float
    date: Optional[str] = None
    label: str = ""
    significance: str = "normal"  # critical, major, normal, minor


@dataclass
class InvalidationRule:
    """무효화 규칙"""
    condition_type: str  # 'price_below', 'price_above', 'time_exceeded'
    threshold: float
    description: str
    
    def is_invalidated(self, current_price: float, current_time: datetime = None) -> bool:
        """무효화 여부 체크"""
        if self.condition_type == 'price_below':
            return current_price < self.threshold
        elif self.condition_type == 'price_above':
            return current_price > self.threshold
        return False


@dataclass
class TargetLevel:
    """목표가 레벨"""
    price: float
    probability: float  # 이 목표 도달 확률
    fib_ratio: float    # 피보나치 비율 (0.618, 1.0, 1.618 등)
    description: str


@dataclass 
class WaveScenarioLive:
    """실시간 파동 시나리오"""
    id: str
    name: str
    description: str
    
    # 파동 구조
    wave_type: WaveType
    current_position: WavePosition
    waves: List[Dict]  # 확정된 파동들 [{'label': '0', 'price': ..., 'date': ...}, ...]
    
    # 확률
    probability: float  # 0.0 ~ 1.0
    confidence: float   # 0.0 ~ 1.0
    
    # 무효화 조건
    invalidation_rules: List[InvalidationRule] = field(default_factory=list)
    is_valid: bool = True
    invalidated_at: Optional[str] = None
    invalidation_reason: str = ""
    
    # 목표가
    targets: List[TargetLevel] = field(default_factory=list)
    stop_loss: Optional[float] = None
    
    # 메타데이터
    created_at: str = ""
    updated_at: str = ""
    update_history: List[Dict] = field(default_factory=list)
    
    def check_invalidation(self, current_price: float) -> bool:
        """무효화 체크 및 상태 업데이트"""
        if not self.is_valid:
            return True
        
        for rule in self.invalidation_rules:
            if rule.is_invalidated(current_price):
                self.is_valid = False
                self.invalidated_at = datetime.now().isoformat()
                self.invalidation_reason = rule.description
                self.probability = 0.0
                return True
        return False
    
    def to_dict(self) -> Dict:
        """딕셔너리 변환"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'wave_type': self.wave_type.value,
            'current_position': self.current_position.value,
            'waves': self.waves,
            'probability': self.probability,
            'confidence': self.confidence,
            'is_valid': self.is_valid,
            'invalidation_rules': [
                {'type': r.condition_type, 'threshold': r.threshold, 'desc': r.description}
                for r in self.invalidation_rules
            ],
            'targets': [
                {'price': t.price, 'prob': t.probability, 'fib': t.fib_ratio, 'desc': t.description}
                for t in self.targets
            ],
            'stop_loss': self.stop_loss
        }


@dataclass
class MarketState:
    """현재 시장 상태"""
    symbol: str
    current_price: float
    timestamp: datetime
    
    # 기술적 지표
    rsi: Optional[float] = None
    macd_signal: Optional[str] = None  # 'bullish', 'bearish', 'neutral'
    volume_trend: Optional[str] = None
    
    # 주요 레벨
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    
    # 피보나치 레벨
    fib_levels: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrackingResult:
    """추적 결과"""
    symbol: str
    timestamp: datetime
    
    # 시나리오들
    scenarios: List[WaveScenarioLive]
    primary_scenario: Optional[WaveScenarioLive]
    
    # 현재 상태
    market_state: MarketState
    
    # 종합 분석
    overall_bias: str  # 'bullish', 'bearish', 'neutral'
    confidence: float
    
    # 의사결정 지원
    key_levels: Dict[str, float]  # {'invalidation': ..., 'target_1': ..., 'stop_loss': ...}
    next_expected_move: str
    
    def to_report(self) -> str:
        """리포트 생성"""
        lines = [
            f"# Elliott Wave Tracker: {self.symbol}",
            f"**Time:** {self.timestamp.strftime('%Y-%m-%d %H:%M')}",
            f"**Price:** ${self.market_state.current_price:,.2f}",
            f"**Bias:** {self.overall_bias.upper()} ({self.confidence:.0%})",
            "",
            "## Active Scenarios",
        ]
        
        valid_scenarios = [s for s in self.scenarios if s.is_valid]
        for s in sorted(valid_scenarios, key=lambda x: -x.probability):
            lines.append(f"### {s.name} ({s.probability:.0%})")
            lines.append(f"- Position: {s.current_position.value}")
            lines.append(f"- Invalidation: ${s.invalidation_rules[0].threshold:,.0f}" if s.invalidation_rules else "")
            if s.targets:
                lines.append(f"- Target: ${s.targets[0].price:,.0f}")
            lines.append("")
        
        lines.extend([
            "## Key Levels",
            f"- Stop Loss: ${self.key_levels.get('stop_loss', 0):,.0f}",
            f"- Target 1: ${self.key_levels.get('target_1', 0):,.0f}",
            "",
            f"**Next Move:** {self.next_expected_move}"
        ])
        
        return "\n".join(lines)
