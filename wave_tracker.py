"""
Elliott Wave Tracker - 통합 실시간 추적 시스템
=============================================
- DualAgentExpert와 통합
- 실시간 시나리오 업데이트
- Cascading 예측
- 영속 기록 저장 (NN 트레이닝용)
- 시나리오 경로 시각화
- 시나리오별 파동 재해석 (v5.2)

리팩토링: 시나리오 생성 → wave_scenarios.py, 시각화 → wave_visualization.py
"""

import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import pandas as pd

# ===== 하위 모듈에서 핵심 클래스 임포트 =====
from experts.elliott.wave_scenarios import (
    WaveInterpretation,
    ScenarioWithInvalidation,
    ScenarioGenerator,
)
from experts.elliott.wave_visualization import WaveVisualizer

# ===== 하위 의존성 임포트 =====
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


class WaveTracker:
    """
    통합 Elliott Wave 추적기

    - 초기 분석 (DualAgentExpert)
    - 다중 시나리오 생성
    - 실시간 업데이트
    - 예측 및 리포트
    - 영속 기록 저장 (NN 트레이닝용)
    - 시나리오 경로 시각화 (WaveVisualizer에 위임)
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

        # Retroactive Wave System (v5.3)
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
        self.df: Optional[pd.DataFrame] = None

        # 시각화 엔진 (자신을 참조)
        self._visualizer = WaveVisualizer(self)

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

        # 3. 시나리오 생성
        scenarios = self.scenario_generator.generate_from_analysis(
            waves=waves,
            current_price=current_price,
            symbol=self.symbol
        )

        for scenario in scenarios:
            self.scenario_tree.add_scenario(scenario)

        # 4. 현재 상태 저장
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
        """ATH가 분석된 W5보다 높으면 파동 구조 자동 조정"""
        wave_map = {w['label']: w for w in waves}
        w5 = wave_map.get('5')

        if not w5:
            return waves

        w5_price = w5.get('price', 0)

        if ath_price > w5_price * 1.05:
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
        """새 가격으로 상태 업데이트"""
        if not self.initialized:
            raise ValueError("Tracker not initialized. Call initialize() first.")

        timestamp = timestamp or datetime.now()

        # 1. 무효화 체크
        invalidated = self.scenario_tree.update_with_price(new_price)

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

        key_levels = {}
        if primary:
            if primary.stop_loss:
                key_levels['stop_loss'] = primary.stop_loss
            if primary.targets:
                key_levels['target_1'] = primary.targets[0].price
            if primary.invalidation_rules:
                key_levels['invalidation'] = primary.invalidation_rules[0].threshold

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
        except Exception:
            return result.to_report()

    # ===== 시각화 위임 메서드 (하위호환) =====

    def get_scenario_chart(self):
        """시나리오 경로 시각화 차트 반환 (WaveVisualizer에 위임)"""
        return self._visualizer.get_scenario_chart()

    def get_multi_timeframe_chart(self):
        """대파동/소파동 멀티 타임프레임 차트 (WaveVisualizer에 위임)"""
        return self._visualizer.get_multi_timeframe_chart()

    def create_quadrant_chart(self, scenarios=None, output_path=None):
        """4분할 시나리오 차트 생성 (WaveVisualizer에 위임)"""
        return self._visualizer.create_quadrant_chart(scenarios, output_path)

    def generate_scenario_charts(self, output_dir='/tmp', include_projections=True):
        """시나리오별 개별 차트 생성 (WaveVisualizer에 위임)"""
        return self._visualizer.generate_scenario_charts(output_dir, include_projections)

    def analyze_and_visualize(self, df=None, output_dir='/tmp'):
        """분석 + 시나리오별 차트 생성 통합 플로우 (WaveVisualizer에 위임)"""
        return self._visualizer.analyze_and_visualize(df, output_dir)

    # ===== 히스토리/통계 메서드 =====

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

    # ===== Self-Correction & Retroactive =====

    def generate_self_corrected_scenarios(
        self,
        df: pd.DataFrame = None,
        max_iterations: int = 2
    ) -> List[Dict]:
        """
        Self-Correction Loop를 적용한 4개 시나리오 생성

        Returns:
            List[Dict]: 수정된 시나리오들
        """
        if not self.initialized or not self.last_analysis:
            return []

        base_waves = self.last_analysis.final_scenario.waves

        if df is None:
            df = self.df

        if isinstance(df.columns, pd.MultiIndex):
            current_price = float(df['Close'].iloc[-1].values[0])
        else:
            current_price = float(df['Close'].iloc[-1])

        scenarios = self.retro_generator.generate_scenarios(
            base_waves=base_waves,
            current_price=current_price,
            df=df
        )

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
        """
        if not self.initialized or not self.last_analysis:
            return None

        base_waves = self.last_analysis.final_scenario.waves
        scenarios = list(self.scenario_tree.scenarios.values())
        current_price = self.current_state.current_price if self.current_state else 0

        conflict = self.retroactive_adjuster.check_conflict(
            scenarios=scenarios,
            current_waves=base_waves,
            current_price=current_price
        )

        if not conflict:
            return None

        proposal = self.retroactive_adjuster.propose_adjustment(
            conflict=conflict,
            current_waves=base_waves,
            current_price=current_price
        )

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

        if auto_reanalyze and proposal.requires_general_expert and self.df is not None:
            print(f"🔄 Auto-triggering General Expert reanalysis...")

            new_analysis = self.dual_agent.analyze(
                df=self.df,
                symbol=self.symbol,
                initial_waves=proposal.adjusted_waves,
                output_dir='/tmp'
            )

            if new_analysis and new_analysis.final_scenario:
                self.last_analysis = new_analysis

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
    ) -> List[ScenarioWithInvalidation]:
        """
        동적 시나리오 생성 (무효화 조건 포함)

        각 시나리오에 명확한 무효화 가격, 방향, 유효 기간을 부여하여
        시장 상황에 따라 적절한 시나리오를 동적 생성

        Returns:
            List[ScenarioWithInvalidation]: 무효화 조건이 포함된 시나리오 리스트
        """
        if base_waves is None:
            if not self.last_analysis:
                return []
            base_waves = self.last_analysis.final_scenario.waves

        if current_price is None:
            current_price = self.current_state.current_price if self.current_state else 0

        raw_scenarios = []

        # 기본 4개 시나리오
        base_scenarios = self.retro_generator.generate_scenarios(
            base_waves=base_waves,
            current_price=current_price,
            df=self.df
        )
        raw_scenarios.extend(base_scenarios)

        # 시장 상황 분석 — 동적 추가 시나리오
        wave_map = {w.get('label'): w for w in base_waves}
        w5 = wave_map.get('5', wave_map.get('W5', {}))
        w0 = wave_map.get('0', wave_map.get('W0', {}))
        w5_price = w5.get('price', 0)
        w0_price = w0.get('price', 0)

        if w5_price > 0:
            price_ratio = current_price / w5_price

            if price_ratio > 0.95:
                raw_scenarios.append({
                    'name': 'Super Cycle Extension',
                    'description': 'ATH 돌파 후 슈퍼사이클 확장',
                    'waves': base_waves,
                    'probability': 0.15,
                    'pattern': 'impulse',
                    'dynamic': True
                })

            elif price_ratio < 0.5:
                raw_scenarios.append({
                    'name': 'New Bull Cycle',
                    'description': 'ABC 완료 후 새로운 상승 사이클',
                    'waves': base_waves,
                    'probability': 0.20,
                    'pattern': 'impulse',
                    'dynamic': True
                })

        # 확률 정규화
        total = sum(s.get('probability', 0.25) for s in raw_scenarios)
        if total > 0:
            for s in raw_scenarios:
                s['probability'] = s.get('probability', 0.25) / total

        # ===== 무효화 조건 래핑 =====
        now = datetime.now()

        # 최근 고점/저점 계산 (df 사용)
        recent_high = w5_price
        recent_low = current_price
        if self.df is not None:
            close_col = 'close' if 'close' in self.df.columns else 'Close'
            tail = self.df.tail(60)
            high_col = 'high' if 'high' in tail.columns else 'High'
            low_col = 'low' if 'low' in tail.columns else 'Low'
            if high_col in tail.columns:
                recent_high = float(tail[high_col].max())
            if low_col in tail.columns:
                recent_low = float(tail[low_col].min())

        wrapped_scenarios = []
        for scenario in raw_scenarios:
            name = scenario.get('name', '').lower()
            pattern = scenario.get('pattern', '')

            # 시나리오 유형별 무효화 조건 설정
            if 'correction' in name or 'abc' in name or 'zigzag' in name:
                # 약세(조정) 시나리오 → 최근 고점 2% 상방 돌파시 무효화
                inv_price = recent_high * 1.02
                inv_dir = 'above'
                valid_days = 90
                condition = f"가격이 ${inv_price:,.0f} (최근 고점 +2%) 상방 돌파시 ABC 조정 시나리오 무효화"
            elif 'extended' in name or pattern == 'impulse':
                # 강세(상승) 시나리오 → 최근 저점 2% 하방 이탈시 무효화
                inv_price = recent_low * 0.98
                inv_dir = 'below'
                valid_days = 120
                condition = f"가격이 ${inv_price:,.0f} (최근 저점 -2%) 하방 이탈시 상승 시나리오 무효화"
            elif 'flat' in name or 'expanded' in name:
                # ABC 플랫 → Wave A 시작 가격 기준
                w_a_start = w5_price if w5_price > 0 else current_price * 1.1
                inv_price = w_a_start * 1.03
                inv_dir = 'above'
                valid_days = 90
                condition = f"가격이 ${inv_price:,.0f} (Wave A 시작 +3%) 돌파시 플랫 시나리오 무효화"
            else:
                # 기본: 양방향 중 더 가까운 쪽
                inv_price = recent_low * 0.95
                inv_dir = 'below'
                valid_days = 60
                condition = f"가격이 ${inv_price:,.0f} 하방 이탈시 무효화"

            wrapped = ScenarioWithInvalidation(
                scenario=scenario,
                invalidation_price=round(inv_price, 2),
                invalidation_direction=inv_dir,
                valid_until=now + timedelta(days=valid_days),
                falsifiable_condition=condition
            )
            wrapped_scenarios.append(wrapped)

        return wrapped_scenarios


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
