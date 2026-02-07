"""
Data Validator - 가격 데이터 + LLM/RAG 기반 검증 에이전트
==============================================
RAG Expert의 시나리오를 실제 데이터로 검증 + Elliott 전문가 LLM 검토
"""

import json
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import pandas as pd

# LLM 클라이언트 - Azure OpenAI 사용
try:
    from knowledge_core.azure_openai_client import AzureOpenAIClient
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# RAG
try:
    from knowledge_core.rag_retriever import RAGRetriever
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

# Local imports
from experts.elliott.rag_expert import ExpertMessage, WaveScenario


# ========== Elliott Wave 기본 규칙 ==========
ELLIOTT_BASIC_RULES = """
## Elliott Wave 불변 규칙 (Inviolable Rules)
1. **Rule 1**: Wave 2 cannot retrace more than 100% of Wave 1
2. **Rule 2**: Wave 3 cannot be the shortest among Waves 1, 3, and 5
3. **Rule 3**: Wave 4 cannot overlap Wave 1's price territory (in impulse waves)

## Elliott Wave 가이드라인 (Guidelines)
1. **Wave 2 Retracement**: Typically 38.2% to 78.6% of Wave 1

2. **Wave 3 Extension**: Usually the longest wave (161.8% to 261.8% of Wave 1)

3. **Wave 4 Retracement**: Typically 23.6% to 50% of Wave 3

4. **Wave 5 Length**: 
   - Often equals Wave 1 in length
   - OR 61.8% to 100% of Wave 1
   - Rarely exceeds Wave 3 (if it does, may be extended 5th)
   
5. **Alternation**: If Wave 2 is sharp, Wave 4 tends to be sideways (and vice versa)

6. **Wave Proportionality**: 
   - Time: Wave 3 ≥ Wave 1 in duration
   - Price: Wave 5 should not be dramatically longer than Wave 1 and Wave 3 combined
   - If Wave 5 > 2x Wave 3, consider if Wave 3 is actually an extended wave

7. **Fibonacci Time Relationships**: Waves tend to relate to each other by Fibonacci ratios in time
"""


@dataclass
class ValidationIssue:
    """검증 이슈"""
    wave_label: str
    issue_type: str  # 'price_mismatch', 'date_order', 'rule_violation', 'ratio_warning'
    description: str
    severity: str  # 'error', 'warning'


class DataValidator:
    """
    데이터 기반 + LLM/RAG Elliott Wave 검증 에이전트
    
    역할:
    1. 제안된 가격이 실제 데이터에 존재하는지 확인 (알고리즘)
    2. 날짜 순서가 올바른지 확인 (알고리즘)
    3. Elliott Wave 불변 규칙 검증 (알고리즘)
    4. LLM + RAG로 가이드라인 및 비율 합리성 검토 (의미론적)
    """
    
    def __init__(self):
        # LLM 초기화 - Azure OpenAI
        if LLM_AVAILABLE:
            self.llm = AzureOpenAIClient()
            if not self.llm.available:
                self.llm = None
        else:
            self.llm = None
        
        # RAG 초기화
        if RAG_AVAILABLE:
            self.rag = RAGRetriever()
            if not self.rag.available:
                self.rag = None
        else:
            self.rag = None
        
        self.available = True  # 알고리즘 검증은 LLM 없이도 가능
    
    def validate_scenario(
        self,
        scenario: WaveScenario,
        df: pd.DataFrame,
        available_pivots: List[Dict],
        previous_messages: List[ExpertMessage] = None
    ) -> ExpertMessage:
        """
        시나리오 검증
        
        Args:
            scenario: RAG Expert의 제안 시나리오
            df: 원본 OHLCV 데이터
            available_pivots: 사용 가능한 피벗 포인트
            previous_messages: 이전 대화
        
        Returns:
            ExpertMessage: 검증 결과
        """
        issues = []
        
        # 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df_work = df.copy()
            df_work.columns = [c[0].lower() for c in df_work.columns]
        else:
            df_work = df
        
        waves = scenario.waves
        
        # 1. 실제 OHLCV 데이터와 가격 일치 확인 (핵심!)
        ohlcv_issues = self._validate_ohlcv_prices(waves, df_work)
        issues.extend(ohlcv_issues)
        
        # 2. 피벗 리스트에 존재 여부 확인
        price_issues = self._validate_prices_exist(waves, available_pivots)
        issues.extend(price_issues)
        
        # 3. 날짜 순서 확인
        date_issues = self._validate_date_order(waves)
        issues.extend(date_issues)
        
        # 4. Elliott Wave 규칙 검증
        rule_issues = self._validate_elliott_rules(waves)
        issues.extend(rule_issues)
        
        # 5. 피보나치 비율 검증
        ratio_issues = self._validate_fibonacci_ratios(waves)
        issues.extend(ratio_issues)
        
        # 6. LLM + RAG 전문가 검토 (파동 비율 합리성 등)
        if self.llm:
            expert_issues = self._llm_expert_review(scenario, df_work)
            issues.extend(expert_issues)
        
        # 결과 생성
        has_errors = any(i.severity == 'error' for i in issues)
        has_warnings = any(i.severity == 'warning' for i in issues)
        
        if not issues:
            return ExpertMessage(
                role='data_validator',
                content="All checks passed. The proposed wave structure is valid.",
                scenario=scenario,
                questions=[],
                agreed=True
            )
        
        # 이슈 포맷팅
        content = self._format_issues(issues)
        
        # LLM으로 종합 피드백 생성
        if self.llm and has_errors:
            content = self._generate_llm_feedback(scenario, issues)
        
        return ExpertMessage(
            role='data_validator',
            content=content,
            scenario=scenario if not has_errors else None,
            questions=self._generate_questions(issues),
            agreed=not has_errors
        )
    
    def _validate_ohlcv_prices(
        self,
        waves: List[Dict],
        df: pd.DataFrame
    ) -> List[ValidationIssue]:
        """실제 OHLCV 데이터와 가격 일치 확인 (핵심!)"""
        issues = []
        tolerance = 0.05  # 5% 허용
        
        for w in waves:
            try:
                date = w['date']
                suggested_price = w['price']
                wave_type = w['type']  # 'high' or 'low'
                
                if date not in df.index:
                    # 날짜가 데이터에 없음 (미래 날짜 or 휴일)
                    continue
                
                row = df.loc[date]
                actual_high = float(row['high'])
                actual_low = float(row['low'])
                
                # wave type에 따라 비교
                if wave_type == 'high':
                    diff = abs(suggested_price - actual_high) / actual_high
                    if diff > tolerance:
                        issues.append(ValidationIssue(
                            wave_label=w['label'],
                            issue_type='price_mismatch',
                            description=f"Wave {w['label']} price ${suggested_price:,.0f} doesn't match actual high ${actual_high:,.0f} on {date} (diff: {diff:.1%})",
                            severity='error'
                        ))
                else:  # 'low'
                    diff = abs(suggested_price - actual_low) / actual_low
                    if diff > tolerance:
                        issues.append(ValidationIssue(
                            wave_label=w['label'],
                            issue_type='price_mismatch',
                            description=f"Wave {w['label']} price ${suggested_price:,.0f} doesn't match actual low ${actual_low:,.0f} on {date} (diff: {diff:.1%})",
                            severity='error'
                        ))
            except Exception as e:
                # 데이터 접근 오류 - 무시
                continue
        
        return issues
    
    def _validate_prices_exist(
        self,
        waves: List[Dict],
        available_pivots: List[Dict]
    ) -> List[ValidationIssue]:
        """가격이 실제 피벗에 존재하는지 확인"""
        issues = []
        
        pivot_prices = {(p['date'], p['type']): p['price'] for p in available_pivots}
        
        for w in waves:
            key = (w['date'], w['type'])
            if key not in pivot_prices:
                # 가격만 확인
                price_exists = any(
                    abs(p['price'] - w['price']) < w['price'] * 0.01  # 1% 허용
                    for p in available_pivots
                )
                if not price_exists:
                    issues.append(ValidationIssue(
                        wave_label=w['label'],
                        issue_type='price_mismatch',
                        description=f"Wave {w['label']} price ${w['price']:,.0f} not found in available pivots",
                        severity='error'
                    ))
        
        return issues
    
    def _validate_date_order(self, waves: List[Dict]) -> List[ValidationIssue]:
        """날짜 순서 확인"""
        issues = []
        
        sorted_waves = sorted(waves, key=lambda x: x['label'])
        
        for i in range(1, len(sorted_waves)):
            prev_date = sorted_waves[i-1]['date']
            curr_date = sorted_waves[i]['date']
            
            if curr_date < prev_date:
                issues.append(ValidationIssue(
                    wave_label=sorted_waves[i]['label'],
                    issue_type='date_order',
                    description=f"Wave {sorted_waves[i]['label']} ({curr_date}) is before Wave {sorted_waves[i-1]['label']} ({prev_date})",
                    severity='error'
                ))
        
        return issues
    
    def _validate_elliott_rules(self, waves: List[Dict]) -> List[ValidationIssue]:
        """Elliott Wave 규칙 검증"""
        issues = []
        
        # 라벨로 인덱싱
        wave_map = {w['label']: w for w in waves}
        
        # 필요한 파동이 모두 있는지 확인
        required = ['0', '1', '2', '3', '4', '5']
        missing = [r for r in required if r not in wave_map]
        if missing:
            issues.append(ValidationIssue(
                wave_label='',
                issue_type='rule_violation',
                description=f"Missing waves: {missing}",
                severity='error'
            ))
            return issues
        
        w0 = wave_map['0']
        w1 = wave_map['1']
        w2 = wave_map['2']
        w3 = wave_map['3']
        w4 = wave_map['4']
        w5 = wave_map['5']
        
        # Rule 1: Wave 2 cannot retrace 100% of Wave 1
        wave1_move = w1['price'] - w0['price']  # 상승 (양수)
        wave2_retrace = w1['price'] - w2['price']  # 하락 (양수)
        
        if wave1_move > 0 and wave2_retrace >= wave1_move:
            issues.append(ValidationIssue(
                wave_label='2',
                issue_type='rule_violation',
                description=f"Wave 2 retraces more than 100% of Wave 1 (W1: ${wave1_move:,.0f}, W2 retrace: ${wave2_retrace:,.0f})",
                severity='error'
            ))
        
        # Rule 2: Wave 3 cannot be the shortest
        wave1_len = abs(w1['price'] - w0['price'])
        wave3_len = abs(w3['price'] - w2['price'])
        wave5_len = abs(w5['price'] - w4['price'])
        
        if wave3_len < wave1_len and wave3_len < wave5_len:
            issues.append(ValidationIssue(
                wave_label='3',
                issue_type='rule_violation',
                description=f"Wave 3 is the shortest (W1: ${wave1_len:,.0f}, W3: ${wave3_len:,.0f}, W5: ${wave5_len:,.0f})",
                severity='error'
            ))
        
        # Rule 3: Wave 4 cannot overlap Wave 1
        if w4['price'] < w1['price']:
            issues.append(ValidationIssue(
                wave_label='4',
                issue_type='rule_violation',
                description=f"Wave 4 low (${w4['price']:,.0f}) overlaps Wave 1 high (${w1['price']:,.0f})",
                severity='error'
            ))
        
        # Rule 4: Wave 5 must exceed Wave 3 (impulse)
        if w5['price'] < w3['price']:
            issues.append(ValidationIssue(
                wave_label='5',
                issue_type='rule_violation',
                description=f"Wave 5 (${w5['price']:,.0f}) does not exceed Wave 3 (${w3['price']:,.0f}) - possible truncation",
                severity='warning'  # 경고 (truncation 가능)
            ))
        
        return issues
    
    def _validate_fibonacci_ratios(self, waves: List[Dict]) -> List[ValidationIssue]:
        """피보나치 비율 검증"""
        issues = []
        
        wave_map = {w['label']: w for w in waves}
        
        if not all(k in wave_map for k in ['0', '1', '2', '3']):
            return issues
        
        w0 = wave_map['0']
        w1 = wave_map['1']
        w2 = wave_map['2']
        w3 = wave_map['3']
        
        # Wave 2 retracement (일반적으로 38.2% ~ 78.6%)
        wave1_move = w1['price'] - w0['price']
        if wave1_move > 0:
            wave2_retrace = (w1['price'] - w2['price']) / wave1_move
            
            if wave2_retrace < 0.236:
                issues.append(ValidationIssue(
                    wave_label='2',
                    issue_type='ratio_warning',
                    description=f"Wave 2 retracement ({wave2_retrace:.1%}) is shallow (<23.6%)",
                    severity='warning'
                ))
            elif wave2_retrace > 0.786:
                issues.append(ValidationIssue(
                    wave_label='2',
                    issue_type='ratio_warning',
                    description=f"Wave 2 retracement ({wave2_retrace:.1%}) is deep (>78.6%)",
                    severity='warning'
                ))
        
        # Wave 3 extension (일반적으로 161.8% ~ 261.8% of Wave 1)
        wave3_move = w3['price'] - w2['price']
        if wave1_move > 0:
            wave3_extension = wave3_move / wave1_move
            
            if wave3_extension < 1.0:
                issues.append(ValidationIssue(
                    wave_label='3',
                    issue_type='ratio_warning',
                    description=f"Wave 3 is shorter than Wave 1 ({wave3_extension:.1%})",
                    severity='warning'
                ))
            elif wave3_extension > 10.0:
                # W3가 W1의 10배 이상이면 구조적 문제
                issues.append(ValidationIssue(
                    wave_label='3',
                    issue_type='ratio_warning',
                    description=f"Wave 3 ({wave3_extension:.0%} of Wave 1) is extremely extended. Consider if Wave 1 is correctly identified - it may be too small or the actual Wave 3 starts earlier.",
                    severity='error'
                ))
        
        # Wave 5 비율 검증 (W4, W5 있을 때)
        if '4' in wave_map and '5' in wave_map:
            w4 = wave_map['4']
            w5 = wave_map['5']
            wave5_move = w5['price'] - w4['price']
            
            if wave1_move > 0 and wave3_move > 0:
                wave5_vs_w1 = wave5_move / wave1_move
                wave5_vs_w3 = wave5_move / wave3_move
                
                # W5가 W3의 2배 이상이면 비정상
                if wave5_vs_w3 > 2.0:
                    issues.append(ValidationIssue(
                        wave_label='5',
                        issue_type='ratio_warning',
                        description=f"Wave 5 is {wave5_vs_w3:.0%} of Wave 3 (unusually long). Consider rechecking Wave 3 identification.",
                        severity='warning'
                    ))
        
        return issues
    
    def _llm_expert_review(
        self,
        scenario: WaveScenario,
        df: pd.DataFrame
    ) -> List[ValidationIssue]:
        """LLM + RAG 기반 Elliott Wave 전문가 검토"""
        issues = []
        
        if not self.llm:
            return issues
        
        # 파동 정보 수집
        waves = scenario.waves
        wave_map = {w['label']: w for w in waves}
        
        # 비율 계산
        ratios_text = ""
        if all(k in wave_map for k in ['0', '1', '2', '3', '4', '5']):
            w0, w1, w2, w3, w4, w5 = [wave_map[str(i)] for i in range(6)]
            
            wave1_len = w1['price'] - w0['price']
            wave3_len = w3['price'] - w2['price']
            wave5_len = w5['price'] - w4['price']
            
            ratios_text = f"""
Wave Length Comparison:
- Wave 1: ${wave1_len:,.0f} ({w0['date']} → {w1['date']})
- Wave 3: ${wave3_len:,.0f} ({w2['date']} → {w3['date']})  [vs W1: {wave3_len/wave1_len:.1%}]
- Wave 5: ${wave5_len:,.0f} ({w4['date']} → {w5['date']})  [vs W1: {wave5_len/wave1_len:.1%}, vs W3: {wave5_len/wave3_len:.1%}]
"""
        
        # RAG에서 Elliott Wave 관련 지식 검색
        rag_knowledge = ""
        if self.rag:
            try:
                docs = self.rag.search("Elliott Wave proportionality wave 5 extension rules", top_k=3)
                if docs:
                    rag_knowledge = "\n".join([f"- {d.get('content', '')[:200]}" for d in docs])
            except:
                pass
        
        # LLM 전문가 검토 프롬프트
        prompt = f"""You are an Elliott Wave validation expert. Review this proposed wave structure.

{ELLIOTT_BASIC_RULES}

**Proposed Wave Structure:**
{json.dumps(waves, indent=2)}

{ratios_text}

**RAG Knowledge (Elliott Wave patterns):**
{rag_knowledge if rag_knowledge else "No additional knowledge available."}

**Task:**
Check if this wave structure follows Elliott Wave guidelines. Focus on:
1. Is Wave 5 proportional to Waves 1 and 3? (W5 > 2x W3 is unusual)
2. Are the time durations reasonable?
3. Does this look like a complete 5-wave impulse?

**Output JSON only:**
{{
  "issues": [
    {{"wave": "<label>", "severity": "error|warning", "description": "<issue>"}}
  ],
  "overall_assessment": "<brief opinion>"
}}"""

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an Elliott Wave validation expert. Always respond in valid JSON format.",
                temperature=0.3,
                max_tokens=500
            )
            
        # JSON 파싱 (robust fallback strategies)
            if response:
                parsed = None
                patterns = [
                    r'```json\s*([\s\S]*?)```',
                    r'```\s*([\s\S]*?)```',
                    r'\{[\s\S]*\}',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, response)
                    if match:
                        json_str = match.group(1) if '```' in pattern else match.group(0)
                        try:
                            parsed = json.loads(json_str.strip())
                            break
                        except json.JSONDecodeError:
                            continue
                
                if parsed is None:
                    try:
                        repaired = re.sub(r',\s*}', '}', response)
                        repaired = re.sub(r',\s*]', ']', repaired)
                        parsed = json.loads(repaired)
                    except:
                        pass
                
                if parsed:
                    for issue in parsed.get('issues', []):
                        issues.append(ValidationIssue(
                            wave_label=issue.get('wave', ''),
                            issue_type='expert_review',
                            description=issue.get('description', ''),
                            severity=issue.get('severity', 'warning')
                        ))
        except Exception as e:
            # 파싱 실패 시 무시
            pass
        
        return issues
    
    def _format_issues(self, issues: List[ValidationIssue]) -> str:
        """이슈 포맷팅"""
        lines = ["**Validation Issues:**"]
        
        errors = [i for i in issues if i.severity == 'error']
        warnings = [i for i in issues if i.severity == 'warning']
        
        if errors:
            lines.append("\n🚫 **Errors (must fix):**")
            for e in errors:
                lines.append(f"- Wave {e.wave_label}: {e.description}")
        
        if warnings:
            lines.append("\n⚠️ **Warnings:**")
            for w in warnings:
                lines.append(f"- Wave {w.wave_label}: {w.description}")
        
        return "\n".join(lines)
    
    def _generate_questions(self, issues: List[ValidationIssue]) -> List[str]:
        """이슈 기반 질문 생성"""
        questions = []
        
        for issue in issues:
            if issue.issue_type == 'rule_violation' and issue.wave_label == '4':
                questions.append("Can you find an alternative Wave 4 low that doesn't overlap Wave 1?")
            elif issue.issue_type == 'date_order':
                questions.append(f"Please check the date for Wave {issue.wave_label}")
            elif issue.issue_type == 'price_mismatch':
                questions.append(f"Wave {issue.wave_label} price doesn't exist - can you select from available pivots?")
        
        return questions
    
    def _generate_llm_feedback(
        self,
        scenario: WaveScenario,
        issues: List[ValidationIssue]
    ) -> str:
        """LLM으로 피드백 생성"""
        issue_text = self._format_issues(issues)
        
        prompt = f"""You are a data validation expert reviewing an Elliott Wave proposal.

**Proposed Waves:**
{json.dumps(scenario.waves, indent=2)}

**Issues Found:**
{issue_text}

**Task:**
Provide constructive feedback for the RAG Expert to improve the wave structure.
Be specific about which pivots need to change and why.

Keep response under 150 words."""

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an Elliott Wave analysis expert.",
                temperature=0.3,
                max_tokens=300
            )
            return response
        except:
            return issue_text


# === 테스트 ===
if __name__ == "__main__":
    print("=== Data Validator Test ===\n")
    
    validator = DataValidator()
    
    # 테스트 시나리오 (Wave 4 overlap 문제 있음)
    test_scenario = WaveScenario(
        waves=[
            {'label': '0', 'price': 15599, 'date': '2022-11-21', 'type': 'low'},
            {'label': '1', 'price': 31815, 'date': '2023-07-13', 'type': 'high'},
            {'label': '2', 'price': 24797, 'date': '2023-06-15', 'type': 'low'},  # 날짜 순서 오류!
            {'label': '3', 'price': 73750, 'date': '2024-03-14', 'type': 'high'},
            {'label': '4', 'price': 49121, 'date': '2024-08-05', 'type': 'low'},
            {'label': '5', 'price': 109115, 'date': '2025-01-20', 'type': 'high'},
        ],
        confidence=0.7,
        reasoning="Test scenario",
        rag_sources=[]
    )
    
    test_pivots = [
        {'date': '2022-11-21', 'price': 15599, 'type': 'low'},
        {'date': '2023-06-15', 'price': 24797, 'type': 'low'},
        {'date': '2023-07-13', 'price': 31815, 'type': 'high'},
        {'date': '2024-03-14', 'price': 73750, 'type': 'high'},
        {'date': '2024-08-05', 'price': 49121, 'type': 'low'},
        {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
    ]
    
    import yfinance as yf
    df = yf.download('BTC-USD', start='2022-01-01', progress=False)
    
    result = validator.validate_scenario(
        scenario=test_scenario,
        df=df,
        available_pivots=test_pivots
    )
    
    print(f"Agreed: {result.agreed}")
    print(f"\nFeedback:\n{result.content}")
    if result.questions:
        print(f"\nQuestions: {result.questions}")
