"""
AI Strategist Report - 전문가급 분석 보고서 생성기
================================================

Gemini Deep Wave Oracle 기반:
- 시나리오 배틀 결과
- 트레이딩 액션 플랜
- 리스크 관리 가이드
- 시각화 데이터
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum
import json

from .strategy_executor import (
    StrategyExecutor, 
    TradingSetup, 
    TradeAction,
    Confluence,
    generate_strategy_from_scenarios
)


class ReportFormat(Enum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    HTML = "html"


@dataclass
class ScenarioBattle:
    """시나리오 배틀 결과"""
    winner: str
    winner_probability: float
    runner_up: str
    runner_up_probability: float
    all_scenarios: List[Dict]
    battle_summary: str


@dataclass
class ActionPlan:
    """트레이딩 액션 플랜"""
    action: str
    entry_zone: str
    stop_loss: str
    take_profits: List[str]
    risk_reward: str
    position_size_suggestion: str
    key_levels: List[Dict]


@dataclass
class AIStrategistReport:
    """AI 전략가 리포트"""
    generated_at: datetime
    symbol: str
    current_price: float
    scenario_battle: ScenarioBattle
    action_plan: ActionPlan
    trading_setup: TradingSetup
    confluences: List[Confluence]
    key_insights: List[str]
    warnings: List[str]
    
    def to_markdown(self) -> str:
        """Markdown 형식으로 출력"""
        lines = []
        
        # 헤더
        lines.append(f"# 📊 AI Elliott Strategist Report")
        lines.append(f"\n**{self.symbol}** | **${self.current_price:,.2f}** | {self.generated_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("\n---\n")
        
        # 1. 시나리오 배틀
        lines.append("## 1. 🥊 시나리오 배틀 (Scenario Battle)")
        lines.append("")
        
        for scenario in self.scenario_battle.all_scenarios:
            status = scenario.get('status', 'ACTIVE')
            prob = scenario.get('probability', 0) * 100
            view = scenario.get('view', 'NEUTRAL')
            
            if status == 'INVALIDATED':
                icon = "❌"
            elif scenario.get('id') == self.scenario_battle.winner:
                icon = "🏆"
            else:
                icon = "🔹"
            
            view_icon = "🟢" if view == 'BULL' else ("🔴" if view == 'BEAR' else "⚪")
            
            lines.append(f"### {icon} {scenario.get('id', 'Unknown')}")
            lines.append(f"- **관점:** {view_icon} {view}")
            lines.append(f"- **확률:** **{prob:.1f}%**")
            lines.append(f"- **현재 웨이브:** {scenario.get('current_wave', 'N/A')}")
            
            inv_price = scenario.get('invalidation_price')
            if inv_price:
                lines.append(f"- **무효화 레벨:** ${inv_price:,.0f}")
            lines.append("")
        
        lines.append(f"> **배틀 요약:** {self.scenario_battle.battle_summary}")
        lines.append("\n---\n")
        
        # 2. 트레이딩 셋업
        lines.append("## 2. 🎯 트레이딩 셋업 (Action Plan)")
        lines.append("")
        
        action_icon = "📈" if self.trading_setup.action == TradeAction.LONG else (
            "📉" if self.trading_setup.action == TradeAction.SHORT else "⏸️"
        )
        
        lines.append(f"### {action_icon} **{self.trading_setup.action.value}**")
        lines.append("")
        lines.append(f"| 항목 | 가격 |")
        lines.append(f"|------|------|")
        lines.append(f"| **진입 (Entry)** | **${self.trading_setup.entry_price:,.2f}** |")
        lines.append(f"| **진입 구간** | ${self.trading_setup.entry_zone[0]:,.2f} ~ ${self.trading_setup.entry_zone[1]:,.2f} |")
        lines.append(f"| **손절 (SL)** | **${self.trading_setup.stop_loss:,.2f}** |")
        
        for tp in self.trading_setup.take_profits:
            lines.append(f"| {tp.get('label', 'TP')} ({tp.get('ratio', 0)*100:.0f}%) | ${tp.get('price', 0):,.2f} |")
        
        lines.append("")
        lines.append(f"**Risk/Reward:** {self.trading_setup.risk_reward:.2f}:1")
        lines.append(f"**Confidence:** {self.trading_setup.confidence*100:.1f}%")
        lines.append("")
        
        # 이유
        lines.append(f"> **근거:** {self.trading_setup.reason}")
        lines.append("\n---\n")
        
        # 3. Confluence
        if self.confluences:
            lines.append("## 3. 🔗 Confluence (교집합 구간)")
            lines.append("")
            lines.append("| 가격 | 강도 | 설명 |")
            lines.append("|------|------|------|")
            
            for conf in self.confluences[:5]:
                strength_bar = "█" * int(conf.strength * 5) + "░" * (5 - int(conf.strength * 5))
                lines.append(f"| ${conf.price_level:,.0f} | {strength_bar} | {conf.description} |")
            
            lines.append("\n---\n")
        
        # 4. 핵심 인사이트
        if self.key_insights:
            lines.append("## 4. 💡 핵심 인사이트")
            lines.append("")
            for insight in self.key_insights:
                lines.append(f"- {insight}")
            lines.append("\n---\n")
        
        # 5. 경고
        if self.warnings:
            lines.append("## 5. ⚠️ 리스크 경고")
            lines.append("")
            for warning in self.warnings:
                lines.append(f"- 🚨 {warning}")
            lines.append("")
        
        # 푸터
        lines.append("---")
        lines.append(f"*Generated by Deep Wave Oracle v2.0*")
        
        return "\n".join(lines)
    
    def to_json(self) -> str:
        """JSON 형식으로 출력"""
        return json.dumps({
            "generated_at": self.generated_at.isoformat(),
            "symbol": self.symbol,
            "current_price": self.current_price,
            "scenario_battle": {
                "winner": self.scenario_battle.winner,
                "winner_probability": self.scenario_battle.winner_probability,
                "runner_up": self.scenario_battle.runner_up,
                "all_scenarios": self.scenario_battle.all_scenarios
            },
            "trading_setup": {
                "action": self.trading_setup.action.value,
                "entry_price": self.trading_setup.entry_price,
                "entry_zone": list(self.trading_setup.entry_zone),
                "stop_loss": self.trading_setup.stop_loss,
                "take_profits": self.trading_setup.take_profits,
                "risk_reward": self.trading_setup.risk_reward,
                "confidence": self.trading_setup.confidence
            },
            "confluences": [
                {
                    "price": c.price_level,
                    "strength": c.strength,
                    "description": c.description
                } for c in self.confluences
            ],
            "key_insights": self.key_insights,
            "warnings": self.warnings
        }, indent=2, ensure_ascii=False)
    
    def to_text(self) -> str:
        """Plain text 형식으로 출력"""
        lines = []
        
        lines.append("=" * 60)
        lines.append(f"📊 AI Elliott Strategist Report")
        lines.append(f"{self.symbol} | ${self.current_price:,.2f}")
        lines.append("=" * 60)
        lines.append("")
        
        # 배틀 결과
        lines.append(f"🏆 WINNER: {self.scenario_battle.winner} ({self.scenario_battle.winner_probability*100:.1f}%)")
        lines.append(f"🥈 Runner-up: {self.scenario_battle.runner_up} ({self.scenario_battle.runner_up_probability*100:.1f}%)")
        lines.append("")
        
        # 트레이딩 셋업
        lines.append(f"📍 ACTION: {self.trading_setup.action.value}")
        lines.append(f"   Entry: ${self.trading_setup.entry_price:,.2f}")
        lines.append(f"   Stop Loss: ${self.trading_setup.stop_loss:,.2f}")
        lines.append(f"   R/R: {self.trading_setup.risk_reward:.2f}:1")
        lines.append("")
        
        # 경고
        for w in self.warnings:
            lines.append(f"⚠️ {w}")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)


class AIStrategistReportGenerator:
    """AI 전략 보고서 생성기"""
    
    def __init__(self, symbol: str, current_price: float, atr: float = None):
        self.symbol = symbol
        self.current_price = current_price
        self.atr = atr or current_price * 0.02
        self.executor = StrategyExecutor(current_price, atr)
    
    def generate_report(
        self,
        scenarios: List[Dict],
        format: ReportFormat = ReportFormat.MARKDOWN
    ) -> AIStrategistReport:
        """
        시나리오 리스트에서 AI 전략 보고서 생성
        
        Args:
            scenarios: 시나리오 리스트
            format: 출력 형식
        
        Returns:
            AIStrategistReport 객체
        """
        # 활성 시나리오만
        active_scenarios = [s for s in scenarios if s.get('status') != 'INVALIDATED']
        
        # Confluence 찾기
        confluences = self.executor.find_confluences(scenarios)
        
        # 트레이딩 셋업 생성
        trading_setup = self.executor.generate_trading_setup(scenarios, confluences)
        
        # 시나리오 배틀 결과
        scenario_battle = self._generate_battle_result(scenarios)
        
        # 인사이트 생성
        key_insights = self._generate_insights(scenarios, confluences, trading_setup)
        
        # 경고 생성
        warnings = self._generate_warnings(scenarios, trading_setup)
        
        return AIStrategistReport(
            generated_at=datetime.now(),
            symbol=self.symbol,
            current_price=self.current_price,
            scenario_battle=scenario_battle,
            action_plan=self._create_action_plan(trading_setup),
            trading_setup=trading_setup,
            confluences=confluences,
            key_insights=key_insights,
            warnings=warnings
        )
    
    def _generate_battle_result(self, scenarios: List[Dict]) -> ScenarioBattle:
        """시나리오 배틀 결과 생성"""
        active = [s for s in scenarios if s.get('status') != 'INVALIDATED']
        
        if not active:
            return ScenarioBattle(
                winner="None",
                winner_probability=0,
                runner_up="None",
                runner_up_probability=0,
                all_scenarios=scenarios,
                battle_summary="모든 시나리오가 무효화됨"
            )
        
        # 확률순 정렬
        sorted_scenarios = sorted(active, key=lambda s: s.get('probability', 0), reverse=True)
        
        winner = sorted_scenarios[0]
        runner_up = sorted_scenarios[1] if len(sorted_scenarios) > 1 else None
        
        # 배틀 요약
        winner_prob = winner.get('probability', 0) * 100
        if winner_prob > 70:
            summary = f"{winner.get('id')} 시나리오가 압도적 우위 ({winner_prob:.0f}%)"
        elif winner_prob > 50:
            summary = f"{winner.get('id')} 약간 우세, 경계 필요"
        else:
            summary = "시나리오 간 팽팽한 균형, 확인 필요"
        
        return ScenarioBattle(
            winner=winner.get('id', 'Unknown'),
            winner_probability=winner.get('probability', 0),
            runner_up=runner_up.get('id', 'None') if runner_up else 'None',
            runner_up_probability=runner_up.get('probability', 0) if runner_up else 0,
            all_scenarios=scenarios,
            battle_summary=summary
        )
    
    def _create_action_plan(self, setup: TradingSetup) -> ActionPlan:
        """액션 플랜 생성"""
        return ActionPlan(
            action=setup.action.value,
            entry_zone=f"${setup.entry_zone[0]:,.2f} ~ ${setup.entry_zone[1]:,.2f}",
            stop_loss=f"${setup.stop_loss:,.2f}",
            take_profits=[f"{tp['label']}: ${tp['price']:,.2f} ({tp['ratio']*100:.0f}%)" for tp in setup.take_profits],
            risk_reward=f"{setup.risk_reward:.2f}:1",
            position_size_suggestion=self._suggest_position_size(setup),
            key_levels=[]
        )
    
    def _suggest_position_size(self, setup: TradingSetup) -> str:
        """포지션 사이즈 제안"""
        if setup.confidence < 0.5:
            return "소량 (계좌의 1-2%)"
        elif setup.confidence < 0.7:
            return "보통 (계좌의 2-3%)"
        else:
            return "적극적 (계좌의 3-5%)"
    
    def _generate_insights(
        self, 
        scenarios: List[Dict], 
        confluences: List[Confluence],
        setup: TradingSetup
    ) -> List[str]:
        """핵심 인사이트 생성"""
        insights = []
        
        # Confluence 인사이트
        if confluences:
            best_conf = confluences[0]
            distance = abs(best_conf.price_level - self.current_price) / self.current_price * 100
            insights.append(f"${best_conf.price_level:,.0f}에 강력한 Confluence 존재 (현재가 대비 {distance:.1f}%)")
        
        # R/R 인사이트
        if setup.risk_reward >= 2:
            insights.append(f"Risk/Reward {setup.risk_reward:.1f}:1로 유리한 셋업")
        elif setup.risk_reward < 1:
            insights.append(f"⚠️ Risk/Reward {setup.risk_reward:.1f}:1로 불리한 셋업")
        
        # 시나리오 일치도
        views = [s.get('view') for s in scenarios if s.get('status') != 'INVALIDATED']
        if views:
            bull_pct = views.count('BULL') / len(views) * 100
            if bull_pct > 70:
                insights.append(f"시나리오 {bull_pct:.0f}%가 상승 관점에 동의")
            elif bull_pct < 30:
                insights.append(f"시나리오 {100-bull_pct:.0f}%가 하락 관점에 동의")
            else:
                insights.append("시나리오 간 의견 분분 - 확인 섹션 필요")
        
        return insights
    
    def _generate_warnings(
        self, 
        scenarios: List[Dict], 
        setup: TradingSetup
    ) -> List[str]:
        """리스크 경고 생성"""
        warnings = []
        
        # 낮은 신뢰도
        if setup.confidence < 0.5:
            warnings.append("신뢰도 50% 미만 - 포지션 축소 권장")
        
        # 무효화 레벨 근접
        for s in scenarios:
            inv = s.get('invalidation_price')
            if inv:
                distance = abs(inv - self.current_price) / self.current_price * 100
                if distance < 3:
                    warnings.append(f"{s.get('id')} 무효화 레벨까지 {distance:.1f}% - 임박")
        
        # 시나리오 총 확률
        total_prob = sum(s.get('probability', 0) for s in scenarios if s.get('status') != 'INVALIDATED')
        if total_prob < 0.5:
            warnings.append("전체 시나리오 신뢰도 낮음 - 관망 권장")
        
        # R/R 경고
        if setup.risk_reward < 1:
            warnings.append("Risk/Reward 1:1 미만 - 불리한 셋업")
        
        return warnings


def generate_ai_report(
    symbol: str,
    current_price: float,
    scenarios: List[Dict],
    format: str = "markdown"
) -> str:
    """
    AI 전략 보고서 생성 (간편 함수)
    
    Usage:
        from experts.elliott.ai_strategist_report import generate_ai_report
        
        report = generate_ai_report(
            symbol="BTC-USD",
            current_price=69000,
            scenarios=[
                {"id": "bull_wave3", "view": "BULL", "probability": 0.7, ...},
                {"id": "bear_c_wave", "view": "BEAR", "probability": 0.3, ...}
            ]
        )
        print(report)  # Markdown 형식 보고서
    """
    generator = AIStrategistReportGenerator(symbol, current_price)
    report = generator.generate_report(scenarios)
    
    if format == "json":
        return report.to_json()
    elif format == "text":
        return report.to_text()
    else:
        return report.to_markdown()
