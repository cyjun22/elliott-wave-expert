"""
Dual Agent Elliott Expert - 듀얼 에이전트 오케스트레이터
======================================================
RAG Expert + Data Validator 교차 검증 + 사용자 확인
"""

import os
import re
import json
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

from experts.elliott.rag_expert import RAGExpert, ExpertMessage, WaveScenario
from experts.elliott.data_validator import DataValidator
from experts.elliott.chart_renderer import ChartRenderer

# 기존 알고리즘
try:
    from experts.elliott.core import ElliottWaveAnalyzer
    ALGO_AVAILABLE = True
except ImportError:
    ALGO_AVAILABLE = False


def _safe_parse_json(content: str, fallback: Dict = None) -> Tuple[Dict, bool]:
    """
    Robust JSON parsing with multiple fallback strategies.
    
    Args:
        content: Raw LLM response string
        fallback: Default value on failure
        
    Returns:
        Tuple of (parsed_dict, success_flag)
    """
    if fallback is None:
        fallback = {}
    
    # Strategy 1: Extract JSON from markdown code blocks
    patterns = [
        r'```json\s*([\s\S]*?)```',  # ```json ... ```
        r'```\s*([\s\S]*?)```',       # ``` ... ```
        r'\{[\s\S]*\}',               # Raw JSON object
    ]
    
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            json_str = match.group(1) if '```' in pattern else match.group(0)
            try:
                return json.loads(json_str.strip()), True
            except json.JSONDecodeError:
                continue
    
    # Strategy 2: Try direct parsing
    try:
        return json.loads(content.strip()), True
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Basic repair (trailing commas, single quotes)
    try:
        repaired = content.strip()
        repaired = re.sub(r',\s*}', '}', repaired)  # Remove trailing commas
        repaired = re.sub(r',\s*]', ']', repaired)
        repaired = repaired.replace("'", '"')       # Single to double quotes
        return json.loads(repaired), True
    except json.JSONDecodeError:
        pass
    
    return fallback, False


@dataclass
class DebateRound:
    """토론 라운드"""
    round_num: int
    rag_message: ExpertMessage
    validator_message: ExpertMessage
    scenario: Optional[WaveScenario]
    chart_path: Optional[str]
    agreed: bool


@dataclass
class UserFeedback:
    """사용자 피드백"""
    approved: bool
    hints: Dict = field(default_factory=dict)
    comments: str = ""


@dataclass
class DualAgentResult:
    """듀얼 에이전트 분석 결과"""
    final_scenario: WaveScenario
    debate_history: List[DebateRound]
    total_rounds: int
    user_approved: bool
    chart_path: str
    confidence: float


class DualAgentExpert:
    """
    듀얼 에이전트 Elliott Wave Expert
    
    흐름:
    1. 알고리즘으로 피벗 추출
    2. RAG Expert가 시나리오 제안
    3. Data Validator가 검증
    4. 합의 또는 5라운드까지 반복
    5. 그래프 + 사용자 확인
    """
    
    MAX_ROUNDS = 5
    
    def __init__(self, pivot_window: int = 20):
        self.rag_expert = RAGExpert()
        self.validator = DataValidator()
        self.renderer = ChartRenderer()
        self.pivot_window = pivot_window
        
        if ALGO_AVAILABLE:
            self.algo = ElliottWaveAnalyzer()
        else:
            self.algo = None
        
        self.available = self.rag_expert.available
    
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        user_hints: Dict = None,
        user_callback: Callable[[str, WaveScenario], UserFeedback] = None,
        output_dir: str = "/tmp"
    ) -> DualAgentResult:
        """
        듀얼 에이전트 분석 실행
        
        Args:
            df: OHLCV 데이터
            symbol: 자산 심볼
            user_hints: 사용자 힌트 (cycle_start, notes 등)
            user_callback: 사용자 확인 콜백 (chart_path, scenario) -> UserFeedback
            output_dir: 차트 저장 디렉토리
        
        Returns:
            DualAgentResult: 분석 결과
        """
        print(f"\n{'='*60}")
        print(f"🎯 Dual Agent Elliott Wave Analysis: {symbol}")
        print(f"{'='*60}\n")
        
        # 피벗 추출
        available_pivots = self._extract_pivots(df)
        data_summary = self._get_data_summary(df)
        
        print(f"📊 Data: {data_summary['start']} ~ {data_summary['end']}")
        print(f"📍 Pivots found: {len(available_pivots)}")
        
        # 토론 루프
        debate_history = []
        previous_messages = []
        current_scenario = None
        agreed = False
        
        for round_num in range(1, self.MAX_ROUNDS + 1):
            print(f"\n{'─'*40}")
            print(f"🔄 Round {round_num}/{self.MAX_ROUNDS}")
            print(f"{'─'*40}")
            
            # RAG Expert 제안
            print("\n📚 RAG Expert proposing...")
            rag_response = self.rag_expert.propose_scenario(
                symbol=symbol,
                data_summary=data_summary,
                available_pivots=available_pivots,
                previous_messages=previous_messages,
                user_hints=user_hints
            )
            
            if rag_response.scenario:
                print(f"   Confidence: {rag_response.scenario.confidence:.0%}")
                print(f"   Waves: {len(rag_response.scenario.waves)}")
            
            # Data Validator 검증
            print("\n📊 Data Validator checking...")
            if rag_response.scenario:
                validator_response = self.validator.validate_scenario(
                    scenario=rag_response.scenario,
                    df=df,
                    available_pivots=available_pivots,
                    previous_messages=previous_messages
                )
            else:
                validator_response = ExpertMessage(
                    role='data_validator',
                    content="No scenario to validate",
                    scenario=None,
                    questions=[],
                    agreed=False
                )
            
            print(f"   Agreed: {validator_response.agreed}")
            if not validator_response.agreed:
                print(f"   Issues: {validator_response.content[:100]}...")
            
            # 차트 생성
            current_scenario = rag_response.scenario
            chart_path = None
            if current_scenario and self.renderer.available:
                chart_path = os.path.join(
                    output_dir, 
                    f"{symbol.replace('-', '_')}_round_{round_num}.png"
                )
                chart_path = self.renderer.render_scenario(
                    df=df,
                    scenario=current_scenario,
                    symbol=symbol,
                    round_num=round_num,
                    save_path=chart_path
                )
                print(f"\n📈 Chart saved: {chart_path}")
            
            # 라운드 기록
            debate_round = DebateRound(
                round_num=round_num,
                rag_message=rag_response,
                validator_message=validator_response,
                scenario=current_scenario,
                chart_path=chart_path,
                agreed=validator_response.agreed
            )
            debate_history.append(debate_round)
            
            # 합의 확인
            if validator_response.agreed:
                print("\n✅ Agents agreed!")
                agreed = True
                break
            
            # 다음 라운드를 위한 메시지 축적
            previous_messages.append(rag_response)
            previous_messages.append(validator_response)
        
        # 최종 결과
        final_scenario = current_scenario
        final_chart = chart_path
        
        # 사용자 확인 (콜백 있으면)
        user_approved = True
        if user_callback and final_scenario:
            print("\n👤 Requesting user confirmation...")
            feedback = user_callback(final_chart, final_scenario)
            user_approved = feedback.approved
            
            if not feedback.approved and feedback.hints:
                # 사용자 힌트 반영하여 재분석 가능
                print(f"   User hints: {feedback.hints}")
        
        # 결과 생성
        result = DualAgentResult(
            final_scenario=final_scenario,
            debate_history=debate_history,
            total_rounds=len(debate_history),
            user_approved=user_approved,
            chart_path=final_chart,
            confidence=final_scenario.confidence if final_scenario else 0
        )
        
        print(f"\n{'='*60}")
        print(f"📋 Analysis Complete")
        print(f"   Rounds: {result.total_rounds}")
        print(f"   Agreed: {agreed}")
        print(f"   Confidence: {result.confidence:.0%}")
        print(f"{'='*60}\n")
        
        return result
    
    def _extract_pivots(self, df: pd.DataFrame) -> List[Dict]:
        """피벗 포인트 추출"""
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0].lower() for c in df_work.columns]
        else:
            df_work = df.copy()
            df_work.columns = [c.lower() for c in df_work.columns]
        
        pivots = []
        window = self.pivot_window
        
        high_col = df_work['high']
        low_col = df_work['low']
        
        # 로컬 고점
        rolling_max = high_col.rolling(window=window, center=True).max()
        local_highs = df_work[high_col == rolling_max]
        
        for idx, row in local_highs.iterrows():
            pivots.append({
                'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                'price': float(row['high']),
                'type': 'high'
            })
        
        # 로컬 저점
        rolling_min = low_col.rolling(window=window, center=True).min()
        local_lows = df_work[low_col == rolling_min]
        
        for idx, row in local_lows.iterrows():
            pivots.append({
                'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                'price': float(row['low']),
                'type': 'low'
            })
        
        # 중복 제거
        seen = set()
        unique = []
        for p in pivots:
            key = (p['date'], p['type'])
            if key not in seen:
                seen.add(key)
                unique.append(p)
        
        unique.sort(key=lambda x: x['date'])
        return unique
    
    def _get_data_summary(self, df: pd.DataFrame) -> Dict:
        """데이터 요약"""
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0].lower() for c in df_work.columns]
        else:
            df_work = df.copy()
            df_work.columns = [c.lower() for c in df_work.columns]
        
        atl_idx = df_work['low'].idxmin()
        ath_idx = df_work['high'].idxmax()
        
        return {
            'start': df_work.index[0].strftime('%Y-%m-%d'),
            'end': df_work.index[-1].strftime('%Y-%m-%d'),
            'atl_date': atl_idx.strftime('%Y-%m-%d'),
            'atl_price': float(df_work.loc[atl_idx, 'low']),
            'ath_date': ath_idx.strftime('%Y-%m-%d'),
            'ath_price': float(df_work.loc[ath_idx, 'high']),
        }
    
    def get_debate_summary(self, result: DualAgentResult) -> str:
        """토론 요약 생성"""
        lines = [
            f"# Elliott Wave Dual-Agent Analysis",
            f"",
            f"## Summary",
            f"- Total Rounds: {result.total_rounds}",
            f"- Final Confidence: {result.confidence:.0%}",
            f"- User Approved: {result.user_approved}",
            f"",
            f"## Final Waves",
        ]
        
        if result.final_scenario:
            for w in result.final_scenario.waves:
                lines.append(f"- Wave {w['label']}: ${w['price']:,.0f} ({w['date']})")
            
            lines.append(f"")
            lines.append(f"## Reasoning")
            lines.append(result.final_scenario.reasoning)
        
        lines.append(f"")
        lines.append(f"## Debate History")
        
        for round_data in result.debate_history:
            lines.append(f"")
            lines.append(f"### Round {round_data.round_num}")
            lines.append(f"**RAG Expert:** {round_data.rag_message.content[:200]}...")
            lines.append(f"**Data Validator:** {round_data.validator_message.content[:200]}...")
            lines.append(f"**Agreed:** {round_data.agreed}")
        
        return "\n".join(lines)
    
    def validate_scenario(
        self,
        scenario_name: str,
        waves: List[Dict],
        current_price: float
    ) -> Dict:
        """
        시나리오별 엘리엇 규칙 검증
        
        Args:
            scenario_name: 시나리오 이름 (Zigzag ABC, Running Flat 등)
            waves: 파동 구조 [{'label': 'W0', 'date': '2023-03', 'price': 19628}, ...]
            current_price: 현재 가격
        
        Returns:
            {
                'valid': True/False,
                'issues': [...],
                'suggestions': [...],
                'probability': 0-100
            }
        """
        if not self.available:
            return {'valid': False, 'issues': ['LLM not available'], 'suggestions': [], 'probability': 0}
        
        # 파동 구조 포맷팅
        wave_str = " → ".join([f"{w['label']}(${w['price']:,.0f})" for w in waves])
        
        prompt = f"""
당신은 엘리엇 파동 이론 전문가입니다. 다음 시나리오의 파동 구조를 검증해주세요.

## 시나리오: {scenario_name}
## 파동 구조: {wave_str}
## 현재 가격: ${current_price:,.0f}

## 엘리엇 임펄스 파동 규칙 (수치로 검증):
1. W2 > W0: W2의 저점이 W0보다 높아야 함 (W2가 W1의 시작점 이하로 되돌리면 안됨)
2. W3 길이: (W3-W2) >= (W1-W0) 그리고 (W3-W2) >= (W5-W4) - W3는 가장 짧지 않아야 함
3. W4 > W1: W4의 저점이 W1의 고점보다 높아야 함 (중첩 금지)

## 중요: 
- 위 규칙은 **가격**으로 직접 비교합니다
- 예: W0=$19,628, W1=$31,815이면, W4의 저점은 반드시 $31,815 초과여야 함
- 현재 구조에서 W4=$74,437이고 W1=$31,815이므로 → W4 > W1 ✓ (규칙 준수)

## 검증 기준:
- 위 3가지 규칙 모두 만족하면 valid=true
- 하나라도 위반하면 valid=false
- 확률은 해당 시나리오가 현재 시장에서 발생할 가능성 (0-100)

JSON 형식으로만 답변:
{{"valid": true/false, "issues": ["문제1"], "suggestions": ["제안1"], "probability": 0-100}}
"""
        
        try:
            client = AzureOpenAI(
                azure_endpoint=os.environ.get('AZURE_OPENAI_ENDPOINT'),
                api_key=os.environ.get('AZURE_OPENAI_API_KEY'),
                api_version='2024-02-15-preview'
            )
            response = client.chat.completions.create(
                model='gpt-4o',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3,
                max_tokens=1000
            )
            
            content = response.choices[0].message.content
            parsed, success = _safe_parse_json(
                content, 
                fallback={'valid': False, 'issues': ['JSON parsing failed'], 'suggestions': [], 'probability': 0}
            )
            return parsed
            
        except Exception as e:
            return {'valid': False, 'issues': [str(e)], 'suggestions': [], 'probability': 0}
    
    def validate_all_scenarios(
        self,
        scenarios: Dict[str, List[Dict]],
        current_price: float
    ) -> Dict[str, Dict]:
        """
        모든 시나리오 일괄 검증
        
        Args:
            scenarios: {'Zigzag ABC': [waves...], 'Running Flat': [waves...], ...}
            current_price: 현재 가격
        
        Returns:
            {'Zigzag ABC': {valid, issues, suggestions, probability}, ...}
        """
        results = {}
        for name, waves in scenarios.items():
            results[name] = self.validate_scenario(name, waves, current_price)
        return results
    
    def correct_scenario(
        self,
        scenario_name: str,
        waves: List[Dict],
        issues: List[str],
        current_price: float,
        df: pd.DataFrame = None
    ) -> Dict:
        """
        LLM에게 파동 수정 제안을 받아 수정된 파동 구조 반환
        
        Args:
            scenario_name: 시나리오 이름
            waves: 현재 파동 구조
            issues: 검증에서 발견된 문제점
            current_price: 현재 가격
            df: 가격 데이터 (피벗 찾기용)
        
        Returns:
            {'corrected_waves': [...], 'explanation': '...'}
        """
        wave_str = " → ".join([f"{w['label']}({w['date']}, ${w['price']:,.0f})" for w in waves])
        issues_str = "\n".join([f"- {issue}" for issue in issues])
        
        prompt = f"""
당신은 엘리엇 파동 전문가입니다. 다음 시나리오에서 규칙 위반이 발견되었습니다.

## 시나리오: {scenario_name}
## 현재 파동: {wave_str}
## 현재 가격: ${current_price:,.0f}

## 발견된 문제:
{issues_str}

## 엘리엇 규칙:
1. W2는 W0 아래로 내려가면 안됨
2. W3는 W1, W5보다 짧을 수 없음
3. W4는 W1 고점 영역에 진입 안됨
4. 임펄스 파동은 5개 하위파동

## ⚠️ 중요 제약:
- **파동은 시간 순서대로 진행해야 함**: W0 < W1 < W2 < W3 < W4 < W5 (날짜 기준)
- **가격과 날짜는 변경 불가** (실제 시장 데이터)
- **레이블만 재배치 가능**: 예) W3 → W3.i, W3.ii, W3.iii 세분화
- 규칙을 만족할 수 없으면 "변경 없음"으로 응답

## 수정 방법:
- 하위파동으로 세분화 (W3 → W3.i/ii/iii/iv/v)
- 현재 위치를 진행 중인 파동으로 표시

JSON으로 응답:
{{"corrected_waves": [{{"label": "W0", "date": "2023-03", "price": 19628}}, ...], "explanation": "수정 이유"}}
"""
        
        try:
            client = AzureOpenAI(
                azure_endpoint=os.environ.get('AZURE_OPENAI_ENDPOINT'),
                api_key=os.environ.get('AZURE_OPENAI_API_KEY'),
                api_version='2024-02-15-preview'
            )
            response = client.chat.completions.create(
                model='gpt-4o',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3,
                max_tokens=1500
            )
            
            content = response.choices[0].message.content
            parsed, success = _safe_parse_json(
                content,
                fallback={'corrected_waves': waves, 'explanation': 'JSON parsing failed'}
            )
            return parsed
        except Exception as e:
            return {'corrected_waves': waves, 'explanation': f'Error: {str(e)}'}
    
    def validate_and_correct(
        self,
        scenario_name: str,
        waves: List[Dict],
        current_price: float,
        max_iterations: int = 3
    ) -> Dict:
        """
        Self-Correction 루프: 검증 → 수정 → 재검증 반복
        
        Args:
            scenario_name: 시나리오 이름
            waves: 초기 파동 구조
            current_price: 현재 가격
            max_iterations: 최대 반복 횟수
        
        Returns:
            {
                'final_waves': [...],
                'valid': True/False,
                'iterations': 반복 횟수,
                'history': [각 반복의 검증 결과]
            }
        """
        current_waves = waves.copy()
        history = []
        seen_issue_sets = set()  # Track seen issue combinations for loop detection
        
        for i in range(max_iterations):
            # 검증
            validation = self.validate_scenario(scenario_name, current_waves, current_price)
            current_issues = tuple(sorted(validation.get('issues', [])))
            
            # Duplicate issue detection: abort if same issues repeat
            if current_issues in seen_issue_sets:
                history.append({
                    'iteration': i + 1,
                    'waves': current_waves.copy(),
                    'validation': validation,
                    'early_exit': 'duplicate_issues_detected'
                })
                break
            seen_issue_sets.add(current_issues)
            
            history.append({
                'iteration': i + 1,
                'waves': current_waves.copy(),
                'validation': validation
            })
            
            # 통과하면 종료
            if validation.get('valid', False):
                return {
                    'final_waves': current_waves,
                    'valid': True,
                    'iterations': i + 1,
                    'probability': validation.get('probability', 0),
                    'history': history
                }
            
            # 수정 제안 받기
            correction = self.correct_scenario(
                scenario_name, current_waves, 
                validation.get('issues', []), current_price
            )
            
            corrected = correction.get('corrected_waves', [])
            if corrected and corrected != current_waves:
                current_waves = corrected
            else:
                # 수정이 없으면 종료
                break
        
        # 최대 반복 도달
        final_validation = self.validate_scenario(scenario_name, current_waves, current_price)
        return {
            'final_waves': current_waves,
            'valid': final_validation.get('valid', False),
            'iterations': max_iterations,
            'probability': final_validation.get('probability', 0),
            'history': history
        }


if __name__ == "__main__":
    print("=== Dual Agent Expert Test ===\n")
    
    import yfinance as yf
    
    df = yf.download('BTC-USD', start='2022-01-01', progress=False)
    
    expert = DualAgentExpert()
    
    if expert.available:
        result = expert.analyze(
            df=df,
            symbol='BTC-USD',
            user_hints={'notes': 'BTC halving cycle based analysis'},
            output_dir='/tmp'
        )
        
        print("\n=== Final Scenario ===")
        if result.final_scenario:
            for w in result.final_scenario.waves:
                print(f"  Wave {w['label']}: ${w['price']:,} ({w['date']})")
        
        print(f"\n📊 Chart: {result.chart_path}")
    else:
        print("❌ Dual Agent Expert not available (LLM required)")
