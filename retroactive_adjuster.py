"""
Retroactive Adjuster - 소급 파동 재해석
========================================
후속 파동 데이터로 이전 파동 라벨 재해석

핵심 기능:
- 현재 시나리오와 이전 분석 간 충돌 감지
- Expanding Diagonal 등 패턴 인식
- General Expert에게 재평가 요청
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum

from experts.elliott.live_tracker import WaveScenarioLive


class ConflictType(Enum):
    """충돌 유형"""
    NONE = "none"
    EXPANDING_DIAGONAL = "expanding_diagonal"  # W5가 W3.iii로 재해석
    EXTENDED_WAVE = "extended_wave"            # W5가 W5.i로 세분화
    TRUNCATION = "truncation"                  # W5가 짧아서 W3가 W5
    FLAT_CORRECTION = "flat_correction"        # ABC 조정 → Flat
    COMPLEX_CORRECTION = "complex_correction"  # ABC → WXYXZ


@dataclass
class Conflict:
    """충돌 정보"""
    conflict_type: ConflictType
    description: str
    affected_waves: List[str]  # 재해석 필요한 파동 라벨
    suggested_relabel: Dict[str, str]  # 예: {"W5": "W3.iii", "W4": "W3.ii"}
    confidence: float = 0.0


@dataclass
class AdjustmentProposal:
    """재해석 제안"""
    original_waves: List[Dict]
    adjusted_waves: List[Dict]
    conflict: Conflict
    reasoning: str
    requires_general_expert: bool = False


class RetroactiveAdjuster:
    """
    소급 파동 재해석 엔진
    
    후속 파동 데이터가 이전 파동 해석과 충돌할 때
    이전 파동 라벨을 재해석합니다.
    
    충돌 발생 시 General Expert 자동 재호출.
    """
    
    # 재평가 트리거 임계값
    CONFLICT_CONFIDENCE_THRESHOLD = 0.6
    
    def __init__(self, db_path: str = None):
        self.conflict_history: List[Dict] = []  # 저장용 Dict 형태
        self.db_path = db_path
        self._load_history()
    
    def _load_history(self):
        """히스토리 로드"""
        if self.db_path:
            import os
            history_file = self.db_path.replace('.db', '_conflicts.json')
            if os.path.exists(history_file):
                try:
                    with open(history_file, 'r') as f:
                        self.conflict_history = json.load(f)
                except:
                    self.conflict_history = []
    
    def _save_history(self):
        """히스토리 저장"""
        if self.db_path:
            history_file = self.db_path.replace('.db', '_conflicts.json')
            with open(history_file, 'w') as f:
                json.dump(self.conflict_history, f, indent=2, default=str)
    
    def log_conflict(self, conflict: Conflict, proposal: 'AdjustmentProposal', current_price: float):
        """충돌 기록 저장"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'conflict_type': conflict.conflict_type.value,
            'description': conflict.description,
            'confidence': conflict.confidence,
            'affected_waves': conflict.affected_waves,
            'suggested_relabel': conflict.suggested_relabel,
            'current_price': current_price,
            'requires_reanalysis': proposal.requires_general_expert
        }
        self.conflict_history.append(record)
        self._save_history()
        return record
    
    def get_conflict_stats(self) -> Dict:
        """충돌 통계"""
        if not self.conflict_history:
            return {'total': 0, 'by_type': {}}
        
        by_type = {}
        for h in self.conflict_history:
            t = h.get('conflict_type', 'unknown')
            by_type[t] = by_type.get(t, 0) + 1
        
        return {
            'total': len(self.conflict_history),
            'by_type': by_type,
            'last_conflict': self.conflict_history[-1] if self.conflict_history else None
        }
        
    def check_conflict(
        self, 
        scenarios: List[WaveScenarioLive],
        current_waves: List[Dict],
        current_price: float
    ) -> Optional[Conflict]:
        """
        시나리오가 기존 파동 해석과 충돌하는지 확인
        
        Args:
            scenarios: 생성된 시나리오들
            current_waves: 현재 확정된 파동 구조
            current_price: 현재 가격
            
        Returns:
            충돌 정보 (없으면 None)
        """
        if not scenarios or not current_waves:
            return None
            
        # 최근 ATH 파동 찾기
        ath_wave = max(current_waves, key=lambda w: w.get('price', 0))
        ath_price = ath_wave.get('price', 0)
        ath_label = ath_wave.get('label', '')
        
        # 케이스 1: Expanding Diagonal 감지
        # 현재가가 ATH 대비 크게 하락했고, 시나리오 중 세분화된 파동이 있는 경우
        if ath_label == 'W5' and current_price < ath_price * 0.7:
            # 50% 이상 시나리오가 세분화(W3.iii 등) 제안
            subdivision_scenarios = [
                s for s in scenarios 
                if any('.' in w.get('label', '') for w in getattr(s, 'confirmed_waves', []))
            ]
            
            if len(subdivision_scenarios) / max(len(scenarios), 1) >= 0.5:
                return Conflict(
                    conflict_type=ConflictType.EXPANDING_DIAGONAL,
                    description=f"ATH({ath_label}=${ath_price:,.0f})가 W5가 아닌 W3.iii일 가능성",
                    affected_waves=['W3', 'W4', 'W5'],
                    suggested_relabel={
                        'W5': 'W3.iii',
                        'W4': 'W3.ii',
                        'W3': 'W3.i'
                    },
                    confidence=0.7
                )
        
        # 케이스 2: Extended Wave 감지
        # ATH 이후 추가 상승 진행 중
        if current_price > ath_price * 1.1:
            return Conflict(
                conflict_type=ConflictType.EXTENDED_WAVE,
                description=f"W5 확장 진행 중 (현재가 > ATH * 1.1)",
                affected_waves=['W5'],
                suggested_relabel={'W5': 'W5.i'},
                confidence=0.6
            )
        
        # 케이스 3: Truncation 감지  
        # W5가 W3보다 낮게 끝남
        w3_wave = next((w for w in current_waves if w.get('label') == 'W3'), None)
        w5_wave = next((w for w in current_waves if w.get('label') == 'W5'), None)
        
        if w3_wave and w5_wave:
            w3_price = w3_wave.get('price', 0)
            w5_price = w5_wave.get('price', 0)
            
            if w5_price < w3_price:
                return Conflict(
                    conflict_type=ConflictType.TRUNCATION,
                    description=f"W5(${w5_price:,.0f}) < W3(${w3_price:,.0f}) - Truncation",
                    affected_waves=['W3', 'W5'],
                    suggested_relabel={'W5': 'W3', 'W3': 'W1'},
                    confidence=0.8
                )
        
        return None
    
    def propose_adjustment(
        self,
        conflict: Conflict,
        current_waves: List[Dict],
        current_price: float
    ) -> AdjustmentProposal:
        """
        충돌 유형에 따른 재해석 제안
        
        Args:
            conflict: 감지된 충돌
            current_waves: 현재 파동 구조
            current_price: 현재 가격
            
        Returns:
            재해석 제안
        """
        adjusted_waves = []
        
        for wave in current_waves:
            new_wave = wave.copy()
            old_label = wave.get('label', '')
            
            if old_label in conflict.suggested_relabel:
                new_wave['label'] = conflict.suggested_relabel[old_label]
                new_wave['original_label'] = old_label  # 원본 보존
                
            adjusted_waves.append(new_wave)
        
        # 추가 파동 필요 시 (예: Expanding Diagonal에서 W3.iv, W3.v)
        if conflict.conflict_type == ConflictType.EXPANDING_DIAGONAL:
            last_wave = adjusted_waves[-1] if adjusted_waves else None
            if last_wave:
                last_date = last_wave.get('date', '')
                # W3.iv 추가 (현재 위치)
                adjusted_waves.append({
                    'label': 'W3.iv',
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'price': current_price,
                    'type': 'intermediate'
                })
        
        reasoning = self._generate_reasoning(conflict)
        
        return AdjustmentProposal(
            original_waves=current_waves,
            adjusted_waves=adjusted_waves,
            conflict=conflict,
            reasoning=reasoning,
            requires_general_expert=(conflict.confidence >= self.CONFLICT_CONFIDENCE_THRESHOLD)
        )
    
    def _generate_reasoning(self, conflict: Conflict) -> str:
        """충돌 유형별 재해석 근거 생성"""
        
        reasonings = {
            ConflictType.EXPANDING_DIAGONAL: """
**Expanding Diagonal 패턴 감지**

Elliott Wave 규칙에 따르면, Expanding Diagonal에서:
- 5파가 3파보다 낮게 끝날 수 있음
- 1-3-5가 점점 커지는 패턴

현재 상황:
- ATH가 W5가 아닌 W3의 하위 파동일 가능성
- W3를 W3.i/W3.ii/W3.iii로 세분화
- 현재 하락 = W3.iv 조정
- W3.v 추가 상승 예상
""",
            ConflictType.EXTENDED_WAVE: """
**Extended Wave 패턴 감지**

W5가 예상보다 길게 확장 중:
- W5.i 완료 후 W5.ii 진행 가능
- 또는 W5 자체가 확장
""",
            ConflictType.TRUNCATION: """
**Truncation 패턴 감지**

W5가 W3보다 낮게 끝남:
- 약세 신호
- 전체 구조 재해석 필요
"""
        }
        
        return reasonings.get(conflict.conflict_type, "충돌 감지됨")
    
    def should_trigger_reevaluation(self, conflict: Conflict) -> bool:
        """General Expert 재평가 필요 여부"""
        return conflict.confidence >= self.CONFLICT_CONFIDENCE_THRESHOLD
    
    def get_conflict_summary(self) -> str:
        """충돌 히스토리 요약"""
        if not self.conflict_history:
            return "No conflicts detected"
            
        lines = ["## Conflict History"]
        for i, conflict in enumerate(self.conflict_history, 1):
            lines.append(f"{i}. {conflict.conflict_type.value}: {conflict.description}")
            
        return "\n".join(lines)


# 4개 표준 시나리오 정의
STANDARD_SCENARIOS = [
    {
        'name': 'Zigzag ABC',
        'description': 'ABC 조정 후 새로운 충격파',
        'pattern': 'corrective',
        'base_probability': 0.30
    },
    {
        'name': 'Running Flat', 
        'description': 'B파가 A파 시작점을 넘는 Flat 조정',
        'pattern': 'corrective',
        'base_probability': 0.30
    },
    {
        'name': 'Expanded Flat',
        'description': 'B파가 시작점을, C파가 A파 끝점을 넘는 Flat',
        'pattern': 'corrective', 
        'base_probability': 0.20
    },
    {
        'name': 'Extended 5th',
        'description': 'W5가 W1+W3보다 긴 확장 5파',
        'pattern': 'impulse',
        'base_probability': 0.20
    }
]


class ScenarioGenerator:
    """
    4개 표준 시나리오 생성기
    
    - Dual Agent Expert의 기본 분석을 바탕으로
    - 4개 시나리오별 파동 구조 생성
    - Self-Correction Loop 적용
    """
    
    def __init__(self, dual_agent_expert=None):
        self.dual_agent = dual_agent_expert
        self.scenarios_templates = STANDARD_SCENARIOS
        
    def generate_scenarios(
        self,
        base_waves: List[Dict],
        current_price: float,
        df=None
    ) -> List[Dict]:
        """
        기본 파동 구조에서 4개 시나리오 생성
        
        Args:
            base_waves: General Expert의 기본 파동 구조
            current_price: 현재 가격
            df: OHLCV 데이터 (Self-Correction용)
            
        Returns:
            4개 시나리오 [{name, waves, probability, valid}]
        """
        scenarios = []
        
        for template in self.scenarios_templates:
            scenario_waves = self._adapt_waves_to_scenario(
                base_waves, 
                template['name'],
                current_price
            )
            
            # Self-Correction 적용 (유효한 waves가 있고 Dual Agent 사용 가능 시)
            if scenario_waves and self.dual_agent and hasattr(self.dual_agent, 'validate_and_correct'):
                try:
                    result = self.dual_agent.validate_and_correct(
                        scenario_name=template['name'],
                        waves=scenario_waves,
                        current_price=current_price,
                        max_iterations=2
                    )
                    if result.get('final_waves'):
                        scenario_waves = result['final_waves']
                except Exception as e:
                    # Self-Correction 실패 시 원본 waves 유지
                    print(f"⚠️ Self-Correction failed for {template['name']}: {e}")
                    
            scenarios.append({
                'name': template['name'],
                'description': template['description'],
                'waves': scenario_waves,
                'probability': template['base_probability'],
                'pattern': template['pattern'],
                'valid': len(scenario_waves) > 0
            })
            
        return scenarios
    
    def _adapt_waves_to_scenario(
        self,
        base_waves: List[Dict],
        scenario_name: str,
        current_price: float
    ) -> List[Dict]:
        """
        시나리오별 파동 구조 적응
        
        각 시나리오에 맞게 기본 파동 라벨 조정
        """
        adapted = []
        
        # base_waves 형식 검증
        if not base_waves or not isinstance(base_waves, list):
            return adapted
        
        # 기본 파동 복사 (Dict인 경우에만)
        for w in base_waves:
            if isinstance(w, dict) and 'label' in w and 'price' in w:
                adapted.append(w.copy())
            elif isinstance(w, dict):
                # label이 없는 경우 건너뛰기
                continue
        
        if not adapted:
            return adapted
        
        # 시나리오별 조정
        if scenario_name == 'Expanded Flat':
            # W3를 W3.i/ii/iii로 세분화
            for i, w in enumerate(adapted):
                label = w.get('label', '')
                if label in ['W3', '3']:
                    w['label'] = 'W3.i'
                elif label in ['W4', '4']:
                    w['label'] = 'W3.ii'
                elif label in ['W5', '5']:
                    w['label'] = 'W3.iii'
                    
        elif scenario_name == 'Extended 5th':
            # W5 이후 추가 파동 예상
            last_wave = adapted[-1] if adapted else None
            if last_wave:
                label = last_wave.get('label', '')
                if 'W5' in label or label == '5':
                    adapted.append({
                        'label': 'W5.ext',
                        'date': 'TBD',
                        'price': current_price * 1.2,  # 예상 목표
                        'type': 'projected'
                    })
                
        elif scenario_name == 'Running Flat':
            # B파가 시작점을 넘음
            for w in adapted:
                label = w.get('label', '')
                if label in ['W4', '4']:
                    w['label'] = 'W3.iv'
                elif label in ['W5', '5']:
                    w['label'] = 'W3.iii'
                    
        return adapted


if __name__ == "__main__":
    print("=== Retroactive Adjuster Test ===\n")
    
    # 테스트 파동 구조
    test_waves = [
        {'label': 'W0', 'date': '2022-11', 'price': 15500},
        {'label': 'W1', 'date': '2023-07', 'price': 31800},
        {'label': 'W2', 'date': '2023-10', 'price': 24800},
        {'label': 'W3', 'date': '2024-03', 'price': 73700},
        {'label': 'W4', 'date': '2024-07', 'price': 56500},
        {'label': 'W5', 'date': '2025-01', 'price': 109000},  # ATH
    ]
    
    current_price = 65000
    
    adjuster = RetroactiveAdjuster()
    
    # 충돌 체크
    conflict = adjuster.check_conflict(
        scenarios=[],  # 빈 시나리오로 테스트
        current_waves=test_waves,
        current_price=current_price
    )
    
    if conflict:
        print(f"🚨 Conflict Detected: {conflict.conflict_type.value}")
        print(f"   Description: {conflict.description}")
        print(f"   Confidence: {conflict.confidence:.0%}")
        
        # 재해석 제안
        proposal = adjuster.propose_adjustment(conflict, test_waves, current_price)
        
        print(f"\n📋 Adjustment Proposal:")
        print(f"   Requires General Expert: {proposal.requires_general_expert}")
        print(f"\n   Adjusted Waves:")
        for w in proposal.adjusted_waves:
            orig = f" (was {w['original_label']})" if 'original_label' in w else ""
            print(f"      {w['label']}: ${w['price']:,.0f}{orig}")
    else:
        print("✅ No conflicts detected")
    
    # 시나리오 생성 테스트
    print("\n\n=== Scenario Generator Test ===\n")
    generator = ScenarioGenerator()
    scenarios = generator.generate_scenarios(test_waves, current_price)
    
    for s in scenarios:
        print(f"📊 {s['name']} ({s['probability']:.0%})")
        for w in s['waves'][:3]:  # 처음 3개만
            print(f"   {w['label']}: ${w['price']:,.0f}")
        print()
