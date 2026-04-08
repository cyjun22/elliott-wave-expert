"""
Strategy Executor - 트레이딩 전략 실행기
==========================================

Gemini Deep Wave Oracle 기반 핵심 모듈:
- Confluence 찾기 (시나리오 교집합)
- Entry/Stop/TP 계산
- Risk/Reward 분석
- 포지션 사이징
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import numpy as np


class TradeAction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"
    CLOSE = "CLOSE"


@dataclass
class TradingSetup:
    """트레이딩 셋업"""
    action: TradeAction
    entry_price: float
    entry_zone: Tuple[float, float]  # (min, max)
    stop_loss: float
    take_profits: List[Dict[str, float]]  # [{"price": x, "ratio": 0.5}]
    risk_reward: float
    confidence: float
    reason: str
    invalidation_scenario: str  # 이 시나리오가 틀리면 손절


@dataclass
class Confluence:
    """시나리오 교집합 (Confluence)"""
    price_level: float
    scenarios: List[str]  # 참여하는 시나리오 ID들
    confluence_type: str  # "support", "resistance", "fib_cluster"
    strength: float  # 0-1
    description: str


class StrategyExecutor:
    """
    전략 실행기 - 시나리오들을 분석하여 트레이딩 전략 도출
    
    핵심 로직:
    1. 살아있는 시나리오들의 교집합(Confluence) 찾기
    2. 최적 Entry/Stop/TP 계산
    3. Risk/Reward 분석
    """
    
    def __init__(self, current_price: float, atr: float = None):
        self.current_price = current_price
        self.atr = atr or current_price * 0.02  # 기본 ATR 2%
        
    def find_confluences(
        self, 
        scenarios: List[Dict],
        tolerance_pct: float = 0.02
    ) -> List[Confluence]:
        """
        여러 시나리오에서 공통으로 나타나는 가격대 찾기
        
        Args:
            scenarios: 시나리오 리스트 (각각 targets, invalidation_levels 포함)
            tolerance_pct: 가격 허용 오차 (2%)
        
        Returns:
            Confluence 리스트 (강도순 정렬)
        """
        # 모든 가격 레벨 수집
        price_levels = []
        
        for scenario in scenarios:
            if scenario.get('status') == 'INVALIDATED':
                continue
                
            scenario_id = scenario.get('id', 'unknown')
            scenario_prob = scenario.get('probability', 0.25)

            # 목표가들
            for target in scenario.get('targets', []):
                price = target.get('price', target) if isinstance(target, dict) else target
                price_levels.append({
                    'price': price,
                    'scenario': scenario_id,
                    'type': 'target',
                    'view': scenario.get('view', 'neutral'),
                    'probability': scenario_prob
                })

            # 무효화 레벨
            inv_price = scenario.get('invalidation_price')
            if inv_price:
                price_levels.append({
                    'price': inv_price,
                    'scenario': scenario_id,
                    'type': 'invalidation',
                    'view': scenario.get('view', 'neutral'),
                    'probability': scenario_prob
                })

            # 피보나치 레벨
            for fib in scenario.get('fibonacci_levels', []):
                price_levels.append({
                    'price': fib.get('price', fib),
                    'scenario': scenario_id,
                    'type': 'fibonacci',
                    'view': scenario.get('view', 'neutral'),
                    'probability': scenario_prob
                })
        
        if not price_levels:
            return []
        
        # 가격 클러스터링
        confluences = self._cluster_prices(price_levels, tolerance_pct)
        
        # 강도순 정렬
        return sorted(confluences, key=lambda c: c.strength, reverse=True)
    
    def _cluster_prices(
        self, 
        price_levels: List[Dict], 
        tolerance_pct: float
    ) -> List[Confluence]:
        """가격 레벨들을 클러스터링하여 Confluence 찾기"""
        if not price_levels:
            return []
        
        # 가격순 정렬
        sorted_levels = sorted(price_levels, key=lambda x: x['price'])
        clusters = []
        current_cluster = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            # 이전 레벨과 가까우면 같은 클러스터
            if abs(level['price'] - current_cluster[-1]['price']) / current_cluster[-1]['price'] < tolerance_pct:
                current_cluster.append(level)
            else:
                if len(current_cluster) >= 2:  # 2개 이상 겹치면 Confluence
                    clusters.append(current_cluster)
                current_cluster = [level]
        
        # 마지막 클러스터
        if len(current_cluster) >= 2:
            clusters.append(current_cluster)
        
        # Confluence 객체로 변환
        confluences = []
        for cluster in clusters:
            avg_price = np.mean([l['price'] for l in cluster])
            scenarios = list(set(l['scenario'] for l in cluster))
            types = list(set(l['type'] for l in cluster))
            
            # 강도 계산: weighted by scenario probability + type diversity
            # Collect max probability per contributing scenario
            scenario_probs = {}
            for lvl in cluster:
                s_id = lvl.get('scenario', 'unknown')
                prob = lvl.get('probability', 0.25)
                if s_id not in scenario_probs or prob > scenario_probs[s_id]:
                    scenario_probs[s_id] = prob
            prob_sum = sum(scenario_probs.values())
            strength = min(1.0, prob_sum * 0.5 + len(types) * 0.15)
            
            # 타입 결정
            if 'invalidation' in types:
                conf_type = 'invalidation_cluster'
            elif 'fibonacci' in types:
                conf_type = 'fib_cluster'
            else:
                conf_type = 'target_cluster'
            
            # 지지/저항 결정
            views = [l['view'] for l in cluster]
            if views.count('BULL') > views.count('BEAR'):
                level_type = 'support'
            else:
                level_type = 'resistance'
            
            confluences.append(Confluence(
                price_level=round(avg_price, 2),
                scenarios=scenarios,
                confluence_type=f"{level_type}_{conf_type}",
                strength=strength,
                description=f"{len(scenarios)}개 시나리오 교차 ({', '.join(types)})"
            ))
        
        return confluences
    
    def generate_trading_setup(
        self,
        scenarios: List[Dict],
        confluences: List[Confluence] = None
    ) -> TradingSetup:
        """
        시나리오와 Confluence를 분석하여 트레이딩 셋업 생성
        
        Args:
            scenarios: 활성 시나리오 리스트
            confluences: Confluence 리스트 (없으면 자동 계산)
        
        Returns:
            TradingSetup 객체
        """
        # 활성 시나리오만 필터
        active_scenarios = [s for s in scenarios if s.get('status') != 'INVALIDATED']
        
        if not active_scenarios:
            return TradingSetup(
                action=TradeAction.WAIT,
                entry_price=0,
                entry_zone=(0, 0),
                stop_loss=0,
                take_profits=[],
                risk_reward=0,
                confidence=0,
                reason="No active scenarios",
                invalidation_scenario=""
            )
        
        # Confluence 찾기
        if confluences is None:
            confluences = self.find_confluences(active_scenarios)
        
        # 최고 확률 시나리오
        best_scenario = max(active_scenarios, key=lambda s: s.get('probability', 0))
        
        # 방향 결정
        view = best_scenario.get('view', 'NEUTRAL')
        action = TradeAction.LONG if view == 'BULL' else (
            TradeAction.SHORT if view == 'BEAR' else TradeAction.WAIT
        )
        
        # Entry Zone 계산
        entry_price, entry_zone = self._calculate_entry(
            best_scenario, confluences, action
        )
        
        # Stop Loss 계산
        stop_loss = self._calculate_stop_loss(best_scenario, action)
        
        # Take Profit 계산
        take_profits = self._calculate_take_profits(best_scenario, action)
        
        # Risk/Reward 계산
        risk_reward = self._calculate_risk_reward(
            entry_price, stop_loss, take_profits
        )
        
        # Confidence 계산
        confidence = self._calculate_confidence(
            best_scenario, confluences, active_scenarios
        )
        
        # 이유 생성
        reason = self._generate_reason(best_scenario, confluences, action)
        
        return TradingSetup(
            action=action,
            entry_price=round(entry_price, 2),
            entry_zone=(round(entry_zone[0], 2), round(entry_zone[1], 2)),
            stop_loss=round(stop_loss, 2),
            take_profits=take_profits,
            risk_reward=round(risk_reward, 2),
            confidence=round(confidence, 2),
            reason=reason,
            invalidation_scenario=best_scenario.get('id', 'unknown')
        )
    
    def _calculate_entry(
        self, 
        scenario: Dict, 
        confluences: List[Confluence],
        action: TradeAction
    ) -> Tuple[float, Tuple[float, float]]:
        """Entry 가격 계산"""
        # 현재가 기준
        base_entry = self.current_price
        
        # Confluence가 현재가 근처에 있으면 사용
        for conf in confluences:
            distance_pct = abs(conf.price_level - self.current_price) / self.current_price
            
            # 현재가에서 5% 이내 Confluence
            if distance_pct < 0.05:
                if action == TradeAction.LONG and conf.price_level < self.current_price:
                    base_entry = conf.price_level  # 하방 Confluence에서 매수
                elif action == TradeAction.SHORT and conf.price_level > self.current_price:
                    base_entry = conf.price_level  # 상방 Confluence에서 매도
                break
        
        # Entry Zone (ATR 기반)
        zone_width = self.atr * 0.5
        entry_zone = (base_entry - zone_width, base_entry + zone_width)
        
        return base_entry, entry_zone
    
    def _calculate_stop_loss(self, scenario: Dict, action: TradeAction) -> float:
        """Stop Loss 계산"""
        # 시나리오의 무효화 레벨 사용
        inv_price = scenario.get('invalidation_price')
        
        if inv_price:
            # 약간의 버퍼 추가
            buffer = self.atr * 0.2
            if action == TradeAction.LONG:
                return inv_price - buffer
            else:
                return inv_price + buffer
        
        # 무효화 레벨이 없으면 ATR 기반
        if action == TradeAction.LONG:
            return self.current_price - (self.atr * 2)
        else:
            return self.current_price + (self.atr * 2)
    
    def _calculate_take_profits(
        self, 
        scenario: Dict, 
        action: TradeAction
    ) -> List[Dict[str, float]]:
        """Take Profit 레벨 계산"""
        targets = scenario.get('targets', [])
        take_profits = []
        
        if not targets:
            # 기본 TP: 1:2, 1:3 비율
            if action == TradeAction.LONG:
                take_profits = [
                    {"price": round(self.current_price * 1.05, 2), "ratio": 0.5, "label": "TP1 (5%)"},
                    {"price": round(self.current_price * 1.10, 2), "ratio": 0.3, "label": "TP2 (10%)"},
                    {"price": round(self.current_price * 1.15, 2), "ratio": 0.2, "label": "TP3 (15%)"},
                ]
            else:
                take_profits = [
                    {"price": round(self.current_price * 0.95, 2), "ratio": 0.5, "label": "TP1 (5%)"},
                    {"price": round(self.current_price * 0.90, 2), "ratio": 0.3, "label": "TP2 (10%)"},
                    {"price": round(self.current_price * 0.85, 2), "ratio": 0.2, "label": "TP3 (15%)"},
                ]
        else:
            # 시나리오 타겟 사용
            ratios = [0.5, 0.3, 0.2]
            for i, target in enumerate(targets[:3]):
                price = target.get('price', target) if isinstance(target, dict) else target
                take_profits.append({
                    "price": round(price, 2),
                    "ratio": ratios[i] if i < len(ratios) else 0.1,
                    "label": target.get('label', f'TP{i+1}') if isinstance(target, dict) else f'TP{i+1}'
                })
        
        return take_profits
    
    def _calculate_risk_reward(
        self, 
        entry: float, 
        stop_loss: float, 
        take_profits: List[Dict]
    ) -> float:
        """Risk/Reward 비율 계산"""
        if not take_profits or entry == stop_loss:
            return 0
        
        risk = abs(entry - stop_loss)
        
        # 가중 평균 Reward
        total_reward = 0
        total_ratio = 0
        for tp in take_profits:
            reward = abs(tp['price'] - entry)
            ratio = tp.get('ratio', 1 / len(take_profits))
            total_reward += reward * ratio
            total_ratio += ratio
        
        avg_reward = total_reward / total_ratio if total_ratio > 0 else 0
        
        return avg_reward / risk if risk > 0 else 0
    
    def _calculate_confidence(
        self, 
        scenario: Dict, 
        confluences: List[Confluence],
        all_scenarios: List[Dict]
    ) -> float:
        """전체 신뢰도 계산"""
        base_confidence = scenario.get('probability', 0.5)
        
        # Confluence 보너스
        if confluences:
            conf_bonus = min(0.15, len(confluences) * 0.05)
            base_confidence += conf_bonus
        
        # 시나리오 일치도 보너스
        same_view = sum(1 for s in all_scenarios if s.get('view') == scenario.get('view'))
        alignment_bonus = (same_view / len(all_scenarios)) * 0.1 if all_scenarios else 0
        base_confidence += alignment_bonus
        
        return min(1.0, base_confidence)
    
    def _generate_reason(
        self, 
        scenario: Dict, 
        confluences: List[Confluence],
        action: TradeAction
    ) -> str:
        """트레이딩 이유 생성"""
        parts = []
        
        # 메인 시나리오
        wave = scenario.get('current_wave', 'Unknown')
        prob = scenario.get('probability', 0) * 100
        parts.append(f"[Main View] {scenario.get('id', 'Unknown')} - {wave} ({prob:.0f}%)")
        
        # Confluence
        if confluences:
            best_conf = confluences[0]
            parts.append(f"[Confluence] ${best_conf.price_level:,.0f} ({best_conf.description})")
        
        # Action 이유
        if action == TradeAction.LONG:
            parts.append("[Action] 상승 관점 우세, 눌림목 매수 추천")
        elif action == TradeAction.SHORT:
            parts.append("[Action] 하락 관점 우세, 반등 시 매도 추천")
        else:
            parts.append("[Action] 관망 - 명확한 셋업 없음")
        
        return " | ".join(parts)


def generate_strategy_from_scenarios(
    scenarios: List[Dict],
    current_price: float,
    atr: float = None
) -> TradingSetup:
    """
    시나리오 리스트에서 트레이딩 전략 생성
    
    Usage:
        from experts.elliott.strategy_executor import generate_strategy_from_scenarios
        
        scenarios = [
            {"id": "bull_wave3", "view": "BULL", "probability": 0.7, ...},
            {"id": "bear_c_wave", "view": "BEAR", "probability": 0.3, ...}
        ]
        
        setup = generate_strategy_from_scenarios(scenarios, current_price=69000)
        print(setup.action)  # TradeAction.LONG
        print(setup.entry_price)  # 68500
        print(setup.stop_loss)  # 65000
    """
    executor = StrategyExecutor(current_price, atr)
    return executor.generate_trading_setup(scenarios)
