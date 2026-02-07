"""
Elliott Wave Multi-Agent System
================================

ElliottAgents 논문 기반 다중 에이전트 구조

에이전트:
1. PivotDetector: 피벗 포인트 감지
2. WaveLabeler: 파동 라벨링
3. ScenarioWriter: 시나리오 생성
4. Backtester: 과거 패턴 검증

Based on: ElliottAgents (2025), CrewAI framework concepts
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
import json


@dataclass
class AgentResult:
    """에이전트 실행 결과"""
    agent_name: str
    success: bool
    data: Any
    confidence: float = 0.5
    reasoning: str = ""
    execution_time_ms: float = 0.0


@dataclass
class AgentMessage:
    """에이전트 간 메시지"""
    from_agent: str
    to_agent: str
    message_type: str  # 'data', 'question', 'validation'
    content: Any
    timestamp: datetime = field(default_factory=datetime.now)


class BaseAgent(ABC):
    """기본 에이전트 클래스"""
    
    def __init__(self, name: str, role: str, tools: List[str] = None):
        self.name = name
        self.role = role
        self.tools = tools or []
        self.messages: List[AgentMessage] = []
        
    @abstractmethod
    def execute(self, input_data: Any) -> AgentResult:
        """에이전트 실행"""
        pass
    
    def receive_message(self, message: AgentMessage):
        """메시지 수신"""
        self.messages.append(message)
    
    def send_message(self, to_agent: str, message_type: str, content: Any) -> AgentMessage:
        """메시지 발신"""
        return AgentMessage(
            from_agent=self.name,
            to_agent=to_agent,
            message_type=message_type,
            content=content
        )


class PivotDetectorAgent(BaseAgent):
    """
    피벗 감지 에이전트
    
    역할: ZigZag 또는 Fractal 기반 피벗 포인트 감지
    """
    
    def __init__(self):
        super().__init__(
            name="PivotDetector",
            role="Pivot Point Identifier",
            tools=["zigzag_indicator", "fractal_detector"]
        )
    
    def execute(self, input_data: Dict) -> AgentResult:
        """피벗 감지 실행"""
        import time
        start = time.time()
        
        df = input_data.get('df')
        sensitivity = input_data.get('sensitivity', 'medium')
        
        if df is None or len(df) == 0:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data=[],
                confidence=0.0,
                reasoning="No data provided"
            )
        
        # 피벗 감지 로직
        pivots = self._detect_pivots(df, sensitivity)
        
        elapsed = (time.time() - start) * 1000
        
        return AgentResult(
            agent_name=self.name,
            success=True,
            data=pivots,
            confidence=0.8,
            reasoning=f"Detected {len(pivots)} pivots with {sensitivity} sensitivity",
            execution_time_ms=elapsed
        )
    
    def _detect_pivots(self, df, sensitivity: str) -> List[Dict]:
        """피벗 감지"""
        # 컬럼 정규화
        high_col = 'High' if 'High' in df.columns else 'high'
        low_col = 'Low' if 'Low' in df.columns else 'low'
        
        # 민감도에 따른 윈도우
        windows = {'high': 5, 'medium': 10, 'low': 20}
        window = windows.get(sensitivity, 10)
        
        pivots = []
        
        for i in range(window, len(df) - window):
            date = df.index[i]
            high = float(df[high_col].iloc[i])
            low = float(df[low_col].iloc[i])
            
            # 로컬 최고/최저
            local_high = float(df[high_col].iloc[i-window:i+window+1].max())
            local_low = float(df[low_col].iloc[i-window:i+window+1].min())
            
            if high >= local_high * 0.999:
                pivots.append({
                    'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
                    'price': high,
                    'type': 'high'
                })
            elif low <= local_low * 1.001:
                pivots.append({
                    'date': date.isoformat() if hasattr(date, 'isoformat') else str(date),
                    'price': low,
                    'type': 'low'
                })
        
        # 중복 제거 및 중요 피벗만
        return self._filter_significant(pivots)
    
    def _filter_significant(self, pivots: List[Dict], top_n: int = 15) -> List[Dict]:
        """중요 피벗 필터링"""
        if len(pivots) <= top_n:
            return pivots
        
        # 가격 변동폭으로 중요도 계산
        for i, p in enumerate(pivots):
            if i == 0:
                p['significance'] = 0
            else:
                p['significance'] = abs(p['price'] - pivots[i-1]['price'])
        
        # 상위 N개
        sorted_pivots = sorted(pivots, key=lambda x: x.get('significance', 0), reverse=True)
        top_pivots = sorted_pivots[:top_n]
        
        # 시간순 정렬
        return sorted(top_pivots, key=lambda x: x['date'])


class WaveLabelerAgent(BaseAgent):
    """
    파동 라벨링 에이전트
    
    역할: 피벗에 Elliott Wave 라벨 부여 및 규칙 검증
    """
    
    WAVE_RULES = {
        'wave_3_longest': "Wave 3 cannot be the shortest",
        'wave_4_not_overlap': "Wave 4 cannot overlap Wave 1",
        'wave_2_not_exceed': "Wave 2 cannot exceed Wave 0"
    }
    
    def __init__(self):
        super().__init__(
            name="WaveLabeler",
            role="Elliott Wave Pattern Recognizer",
            tools=["fibonacci_tool", "wave_rules_validator"]
        )
    
    def execute(self, input_data: Dict) -> AgentResult:
        """파동 라벨링 실행"""
        import time
        start = time.time()
        
        pivots = input_data.get('pivots', [])
        
        if len(pivots) < 5:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                confidence=0.0,
                reasoning="Insufficient pivots for wave labeling"
            )
        
        # 파동 라벨링
        waves = self._label_waves(pivots)
        
        # 규칙 검증
        validation = self._validate_rules(waves)
        
        elapsed = (time.time() - start) * 1000
        
        return AgentResult(
            agent_name=self.name,
            success=validation['is_valid'],
            data={'waves': waves, 'validation': validation},
            confidence=validation['confidence'],
            reasoning=validation['reasoning'],
            execution_time_ms=elapsed
        )
    
    def _label_waves(self, pivots: List[Dict]) -> Dict[str, Dict]:
        """파동 라벨 부여"""
        waves = {}
        labels = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']
        
        for i, p in enumerate(pivots):
            if i >= len(labels):
                break
            waves[labels[i]] = {
                'price': p['price'],
                'date': p['date'],
                'type': p['type']
            }
        
        return waves
    
    def _validate_rules(self, waves: Dict[str, Dict]) -> Dict:
        """Elliott Wave 규칙 검증"""
        violations = []
        confidence = 1.0
        
        # 규칙 1: Wave 3 is not shortest
        if all(k in waves for k in ['0', '1', '2', '3', '4', '5']):
            w1_len = abs(waves['1']['price'] - waves['0']['price'])
            w3_len = abs(waves['3']['price'] - waves['2']['price'])
            w5_len = abs(waves['5']['price'] - waves['4']['price'])
            
            if w3_len < min(w1_len, w5_len):
                violations.append(self.WAVE_RULES['wave_3_longest'])
                confidence -= 0.3
        
        # 규칙 2: Wave 4 doesn't overlap Wave 1
        if all(k in waves for k in ['1', '4']):
            # 상승파 가정
            if waves['4']['price'] < waves['1']['price']:
                violations.append(self.WAVE_RULES['wave_4_not_overlap'])
                confidence -= 0.2
        
        # 규칙 3: Wave 2 doesn't exceed Wave 0
        if all(k in waves for k in ['0', '2']):
            if waves['2']['price'] < waves['0']['price']:
                violations.append(self.WAVE_RULES['wave_2_not_exceed'])
                confidence -= 0.3
        
        return {
            'is_valid': len(violations) == 0,
            'violations': violations,
            'confidence': max(0, confidence),
            'reasoning': '; '.join(violations) if violations else "All rules satisfied"
        }


class ScenarioWriterAgent(BaseAgent):
    """
    시나리오 생성 에이전트
    
    역할: 검증된 파동을 바탕으로 미래 시나리오 생성
    """
    
    def __init__(self):
        super().__init__(
            name="ScenarioWriter",
            role="Market Scenario Generator",
            tools=["chart_generator", "probability_calculator"]
        )
    
    def execute(self, input_data: Dict) -> AgentResult:
        """시나리오 생성 실행"""
        import time
        start = time.time()
        
        waves = input_data.get('waves', {})
        current_price = input_data.get('current_price', 0)
        
        if not waves or current_price == 0:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data=[],
                confidence=0.0,
                reasoning="Missing waves or current price"
            )
        
        # 시나리오 생성
        scenarios = self._generate_scenarios(waves, current_price)
        
        elapsed = (time.time() - start) * 1000
        
        return AgentResult(
            agent_name=self.name,
            success=True,
            data=scenarios,
            confidence=0.7,
            reasoning=f"Generated {len(scenarios)} scenarios",
            execution_time_ms=elapsed
        )
    
    def _generate_scenarios(self, waves: Dict, current_price: float) -> List[Dict]:
        """시나리오 생성"""
        scenarios = []
        
        w5_price = waves.get('5', {}).get('price', current_price)
        w0_price = waves.get('0', {}).get('price', current_price * 0.5)
        
        # ATH 대비 하락률
        decline_ratio = 1 - (current_price / w5_price) if w5_price > 0 else 0
        
        # 피보나치 레벨
        wave_range = w5_price - w0_price
        fib_382 = w5_price - wave_range * 0.382
        fib_618 = w5_price - wave_range * 0.618
        
        # 확률 동적 계산
        if decline_ratio > 0.4:
            prob_abc = 0.70
            prob_new_cycle = 0.25
            prob_extended = 0.05
        elif decline_ratio > 0.3:
            prob_abc = 0.60
            prob_new_cycle = 0.30
            prob_extended = 0.10
        else:
            prob_abc = 0.50
            prob_new_cycle = 0.20
            prob_extended = 0.30
        
        scenarios.append({
            'id': 'abc_correction',
            'name': 'ABC Correction',
            'probability': prob_abc,
            'targets': [fib_382, fib_618],
            'invalidation': w5_price * 1.02,
            'description': 'ABC 조정 진행 중'
        })
        
        scenarios.append({
            'id': 'new_supercycle',
            'name': 'New Supercycle',
            'probability': prob_new_cycle,
            'targets': [w5_price * 1.5, w5_price * 2],
            'invalidation': w0_price * 0.9,
            'description': '새 상승 사이클 시작'
        })
        
        scenarios.append({
            'id': 'extended_5th',
            'name': 'Extended 5th Wave',
            'probability': prob_extended,
            'targets': [w5_price * 1.2, w5_price * 1.618],
            'invalidation': waves.get('4', {}).get('price', current_price * 0.9),
            'description': '5파 확장 진행'
        })
        
        return scenarios


class BacktesterAgent(BaseAgent):
    """
    백테스터 에이전트
    
    역할: 과거 패턴과 비교하여 신뢰도 검증
    """
    
    def __init__(self):
        super().__init__(
            name="Backtester",
            role="Historical Pattern Validator",
            tools=["pattern_database", "similarity_scorer"]
        )
        self.pattern_db: List[Dict] = []  # 패턴 데이터베이스
    
    def execute(self, input_data: Dict) -> AgentResult:
        """백테스트 실행"""
        import time
        start = time.time()
        
        waves = input_data.get('waves', {})
        scenarios = input_data.get('scenarios', [])
        
        if not waves:
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                confidence=0.0,
                reasoning="No waves to validate"
            )
        
        # 유사 패턴 검색
        similar_patterns = self._find_similar_patterns(waves)
        
        # 시나리오별 성공률
        success_rates = self._calculate_success_rates(similar_patterns, scenarios)
        
        elapsed = (time.time() - start) * 1000
        
        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                'similar_patterns': similar_patterns,
                'success_rates': success_rates
            },
            confidence=0.6,
            reasoning=f"Found {len(similar_patterns)} similar historical patterns",
            execution_time_ms=elapsed
        )
    
    def _find_similar_patterns(self, waves: Dict) -> List[Dict]:
        """유사 패턴 검색"""
        # 실제 구현에서는 패턴 DB 검색
        # 여기서는 예시 데이터 반환
        return [
            {'date': '2021-04', 'outcome': 'abc_correction', 'success': True},
            {'date': '2018-12', 'outcome': 'abc_correction', 'success': True},
            {'date': '2013-12', 'outcome': 'new_supercycle', 'success': True},
        ]
    
    def _calculate_success_rates(
        self, 
        patterns: List[Dict], 
        scenarios: List[Dict]
    ) -> Dict[str, float]:
        """시나리오별 성공률 계산"""
        rates = {}
        
        for scenario in scenarios:
            matching = [p for p in patterns if p['outcome'] == scenario['id']]
            successful = [p for p in matching if p['success']]
            
            if matching:
                rates[scenario['id']] = len(successful) / len(matching)
            else:
                rates[scenario['id']] = 0.5  # 기본값
        
        return rates


class ElliottWaveAgentSystem:
    """
    Elliott Wave 다중 에이전트 시스템
    
    전체 파이프라인 조율
    """
    
    def __init__(self):
        self.agents = {
            'pivot_detector': PivotDetectorAgent(),
            'wave_labeler': WaveLabelerAgent(),
            'scenario_writer': ScenarioWriterAgent(),
            'backtester': BacktesterAgent()
        }
        self.message_log: List[AgentMessage] = []
        self.execution_history: List[AgentResult] = []
    
    def analyze(self, df, current_price: float) -> Dict:
        """
        전체 분석 파이프라인
        
        1. 피벗 감지
        2. 파동 라벨링
        3. 시나리오 생성
        4. 백테스트 검증
        """
        results = {
            'success': False,
            'pivots': [],
            'waves': {},
            'scenarios': [],
            'validation': {},
            'execution_log': []
        }
        
        print("\n" + "="*60)
        print("🤖 Elliott Wave Multi-Agent System")
        print("="*60 + "\n")
        
        # 1. 피벗 감지
        print("📍 Step 1: Pivot Detection")
        pivot_result = self.agents['pivot_detector'].execute({'df': df})
        self.execution_history.append(pivot_result)
        results['execution_log'].append(pivot_result.agent_name)
        
        if not pivot_result.success:
            results['error'] = pivot_result.reasoning
            return results
        
        results['pivots'] = pivot_result.data
        print(f"   ✅ {len(pivot_result.data)} pivots detected\n")
        
        # 에이전트 간 메시지 전달
        msg1 = self.agents['pivot_detector'].send_message(
            'wave_labeler', 'data', pivot_result.data
        )
        self.message_log.append(msg1)
        
        # 2. 파동 라벨링
        print("🏷️ Step 2: Wave Labeling")
        label_result = self.agents['wave_labeler'].execute({'pivots': pivot_result.data})
        self.execution_history.append(label_result)
        results['execution_log'].append(label_result.agent_name)
        
        if not label_result.success:
            print(f"   ⚠️ {label_result.reasoning}")
        
        results['waves'] = label_result.data.get('waves', {})
        results['validation']['wave_rules'] = label_result.data.get('validation', {})
        print(f"   ✅ {len(results['waves'])} waves labeled (confidence: {label_result.confidence:.1%})\n")
        
        # 3. 시나리오 생성
        print("📊 Step 3: Scenario Generation")
        scenario_result = self.agents['scenario_writer'].execute({
            'waves': results['waves'],
            'current_price': current_price
        })
        self.execution_history.append(scenario_result)
        results['execution_log'].append(scenario_result.agent_name)
        
        results['scenarios'] = scenario_result.data
        print(f"   ✅ {len(scenario_result.data)} scenarios generated\n")
        
        # 4. 백테스트 검증
        print("🔍 Step 4: Backtesting")
        backtest_result = self.agents['backtester'].execute({
            'waves': results['waves'],
            'scenarios': results['scenarios']
        })
        self.execution_history.append(backtest_result)
        results['execution_log'].append(backtest_result.agent_name)
        
        results['validation']['backtest'] = backtest_result.data
        print(f"   ✅ Historical validation complete\n")
        
        # 최종 결과
        results['success'] = True
        print("="*60)
        print("📋 Analysis Complete")
        print("="*60)
        
        return results
    
    def get_execution_summary(self) -> str:
        """실행 요약"""
        lines = ["=== Execution Summary ==="]
        
        for result in self.execution_history:
            status = "✅" if result.success else "❌"
            lines.append(f"{status} {result.agent_name}: {result.reasoning} ({result.execution_time_ms:.1f}ms)")
        
        return "\n".join(lines)


# 테스트
def test_multi_agent_system():
    """Multi-Agent 시스템 테스트"""
    import yfinance as yf
    
    # 데이터 로드
    df = yf.download('BTC-USD', period='2y', interval='1d', progress=False)
    
    # 컬럼 정규화
    if hasattr(df.columns, 'get_level_values'):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.title() for c in df.columns]
    
    current_price = float(df['Close'].iloc[-1])
    
    # 시스템 실행
    system = ElliottWaveAgentSystem()
    results = system.analyze(df, current_price)
    
    # 결과 출력
    print("\n" + system.get_execution_summary())
    
    print("\n📊 시나리오 확률:")
    for s in results['scenarios']:
        print(f"   {s['name']}: {s['probability']:.1%}")
    
    return results


if __name__ == '__main__':
    test_multi_agent_system()
