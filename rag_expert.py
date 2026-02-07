"""
RAG Expert - Elliott Wave 이론 기반 시나리오 생성
=================================================
RAG 지식과 Elliott Wave 이론을 활용한 시나리오 제안
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

# LLM 클라이언트 - Azure OpenAI 사용
try:
    from knowledge_core.azure_openai_client import AzureOpenAIClient
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# RAG 검색
try:
    from knowledge_core.rag_retriever import RAGRetriever
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False


@dataclass
class WaveScenario:
    """파동 시나리오"""
    waves: List[Dict]  # [{'label': '0', 'price': 15599, 'date': '2022-11-21', 'type': 'low'}, ...]
    confidence: float
    reasoning: str
    rag_sources: List[str]


@dataclass
class ExpertMessage:
    """에이전트 간 메시지"""
    role: str  # 'rag_expert' or 'data_validator'
    content: str
    scenario: Optional[WaveScenario]
    questions: List[str]
    agreed: bool


class RAGExpert:
    """
    RAG 기반 Elliott Wave 이론 전문가
    
    역할:
    1. Elliott Wave 기본 규칙 적용
    2. RAG로 자산별 특성 검색
    3. 시나리오 제안 및 수정
    """
    
    # 기본 Elliott Wave 규칙
    BASIC_RULES = """
**Elliott Wave Basic Rules (MUST follow):**

1. **Wave 2 Rule**: Cannot retrace more than 100% of Wave 1
   - If Wave 1 goes from $100 to $200, Wave 2 cannot go below $100

2. **Wave 3 Rule**: Cannot be the shortest among Waves 1, 3, and 5
   - Wave 3 is typically the longest and most powerful

3. **Wave 4 Rule**: Cannot overlap with Wave 1's price territory
   - Wave 4's low must stay above Wave 1's high
   - Example: If Wave 1 high is $200, Wave 4 low must be > $200

4. **Wave 5 Rule**: Must exceed Wave 3's end in impulse waves
   - In truncated cases, Wave 5 may fail to exceed Wave 3

5. **Alternation Guideline**: Wave 2 and Wave 4 should differ in form
   - If Wave 2 is sharp, Wave 4 tends to be sideways (and vice versa)
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
            try:
                self.rag = RAGRetriever()
                if not self.rag.available:
                    self.rag = None
            except:
                self.rag = None
        else:
            self.rag = None
        
        self.available = self.llm is not None
    
    def propose_scenario(
        self,
        symbol: str,
        data_summary: Dict,
        available_pivots: List[Dict],
        previous_messages: List[ExpertMessage] = None,
        user_hints: Dict = None
    ) -> ExpertMessage:
        """
        시나리오 제안
        
        Args:
            symbol: 자산 심볼
            data_summary: 데이터 요약 {'atl': ..., 'ath': ..., 'start': ..., 'end': ...}
            available_pivots: 사용 가능한 피벗 포인트
            previous_messages: 이전 대화 (Data Validator 피드백 등)
            user_hints: 사용자 힌트 {'cycle_start': ..., 'notes': ...}
        
        Returns:
            ExpertMessage: 제안 메시지
        """
        if not self.llm:
            return self._fallback_scenario(symbol, data_summary, available_pivots)
        
        # RAG 지식 검색
        rag_context, rag_sources = self._search_rag(symbol)
        
        # 이전 대화 포맷
        conversation_history = self._format_history(previous_messages)
        
        # 피벗 포인트 포맷
        pivot_text = self._format_pivots(available_pivots)
        
        # 사용자 힌트 포맷
        hint_text = ""
        if user_hints:
            hints = []
            if 'cycle_start' in user_hints:
                hints.append(f"- Cycle start: {user_hints['cycle_start']} at ${user_hints.get('cycle_start_price', 'N/A')}")
            if 'expected_peak_date' in user_hints:
                hints.append(f"- Expected peak: {user_hints['expected_peak_date']}")
            if 'notes' in user_hints:
                hints.append(f"- Notes: {user_hints['notes']}")
            hint_text = "\n".join(hints)
        
        prompt = f"""You are an Elliott Wave theory expert using RAG knowledge.

{self.BASIC_RULES}

**Asset:** {symbol}
**Data Period:** {data_summary.get('start', 'N/A')} to {data_summary.get('end', 'N/A')}
**ATL:** ${data_summary.get('atl_price', 0):,.0f} on {data_summary.get('atl_date', 'N/A')}
**ATH:** ${data_summary.get('ath_price', 0):,.0f} on {data_summary.get('ath_date', 'N/A')}

**RAG Knowledge (asset-specific):**
{rag_context if rag_context else "No specific knowledge found. Use general Elliott Wave theory."}

{f"**User Hints:**{chr(10)}{hint_text}" if hint_text else ""}

**Available Pivot Points (you MUST select from this list):**
{pivot_text}

{f"**Previous Discussion:**{chr(10)}{conversation_history}" if conversation_history else ""}

**Task:**
1. Based on Elliott Wave theory and RAG knowledge, propose a 5-wave impulse structure
2. Select ONLY from the available pivot points above
3. Explain your reasoning using theory and asset characteristics
4. If previous feedback exists, address it

**Output JSON only:**
{{
  "waves": [
    {{"label": "0", "price": <number>, "date": "<YYYY-MM-DD>", "type": "low"}},
    {{"label": "1", "price": <number>, "date": "<YYYY-MM-DD>", "type": "high"}},
    {{"label": "2", "price": <number>, "date": "<YYYY-MM-DD>", "type": "low"}},
    {{"label": "3", "price": <number>, "date": "<YYYY-MM-DD>", "type": "high"}},
    {{"label": "4", "price": <number>, "date": "<YYYY-MM-DD>", "type": "low"}},
    {{"label": "5", "price": <number>, "date": "<YYYY-MM-DD>", "type": "high"}}
  ],
  "confidence": <0.0-1.0>,
  "reasoning": "<explanation using Elliott theory and RAG knowledge>",
  "questions_for_validator": ["<any questions about data validity>"]
}}"""

        try:
            response = self.llm.generate(
                prompt=prompt,
                system_prompt="You are an Elliott Wave analysis expert. Always respond in valid JSON format.",
                temperature=0.3,
                max_tokens=800
            )
            
            result = self._parse_json(response)
            
            scenario = WaveScenario(
                waves=result.get('waves', []),
                confidence=result.get('confidence', 0.5),
                reasoning=result.get('reasoning', ''),
                rag_sources=rag_sources
            )
            
            return ExpertMessage(
                role='rag_expert',
                content=result.get('reasoning', ''),
                scenario=scenario,
                questions=result.get('questions_for_validator', []),
                agreed=False
            )
            
        except Exception as e:
            print(f"⚠️ RAG Expert error: {e}")
            return self._fallback_scenario(symbol, data_summary, available_pivots)
    
    def respond_to_feedback(
        self,
        feedback: ExpertMessage,
        symbol: str,
        available_pivots: List[Dict]
    ) -> ExpertMessage:
        """Data Validator의 피드백에 응답"""
        # 피드백을 이전 메시지에 포함하여 다시 제안
        return self.propose_scenario(
            symbol=symbol,
            data_summary={},
            available_pivots=available_pivots,
            previous_messages=[feedback]
        )
    
    def _search_rag(self, symbol: str) -> tuple:
        """RAG 지식 검색"""
        if not self.rag:
            return "", []
        
        queries = [
            f"{symbol} market cycle characteristics",
            f"{symbol} Elliott Wave historical patterns",
            f"cryptocurrency halving cycle" if 'BTC' in symbol.upper() else f"{symbol} economic cycle"
        ]
        
        all_results = []
        sources = []
        
        for query in queries:
            result = self.rag.search(query, top_k=2)
            if result['available'] and result['summary']:
                all_results.append(result['summary'])
                sources.extend([d.get('source', 'unknown') for d in result.get('documents', [])])
        
        return "\n".join(all_results), list(set(sources))
    
    def _format_history(self, messages: List[ExpertMessage]) -> str:
        """이전 대화 포맷"""
        if not messages:
            return ""
        
        lines = []
        for msg in messages:
            role = "Data Validator" if msg.role == 'data_validator' else "RAG Expert"
            lines.append(f"**{role}:** {msg.content}")
            if msg.questions:
                lines.append(f"  Questions: {', '.join(msg.questions)}")
        
        return "\n".join(lines)
    
    def _format_pivots(self, pivots: List[Dict]) -> str:
        """피벗 포인트 포맷"""
        lines = []
        for p in pivots:
            lines.append(f"- {p['date']}: ${p['price']:,.0f} ({p['type']})")
        return "\n".join(lines)
    
    def _parse_json(self, response: str) -> Dict:
        """LLM 응답에서 JSON 추출 (Robust parsing with fallbacks)"""
        # Strategy 1: Extract from markdown code blocks
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
                    return json.loads(json_str.strip())
                except json.JSONDecodeError:
                    continue
        
        # Strategy 2: Direct parsing
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            pass
        
        # Strategy 3: Basic repair
        try:
            repaired = re.sub(r',\s*}', '}', response)
            repaired = re.sub(r',\s*]', ']', repaired)
            repaired = repaired.replace("'", '"')
            return json.loads(repaired)
        except json.JSONDecodeError:
            return {}
    
    def _fallback_scenario(
        self,
        symbol: str,
        data_summary: Dict,
        available_pivots: List[Dict]
    ) -> ExpertMessage:
        """LLM 실패 시 알고리즘 기반 5파동 시나리오 생성"""
        # 날짜순 정렬
        sorted_pivots = sorted(available_pivots, key=lambda x: x['date'])
        
        lows = [p for p in sorted_pivots if p['type'] == 'low']
        highs = [p for p in sorted_pivots if p['type'] == 'high']
        
        if len(lows) < 3 or len(highs) < 3:
            return ExpertMessage(
                role='rag_expert',
                content="Insufficient pivot data for wave structure",
                scenario=None,
                questions=[],
                agreed=False
            )
        
        # 1단계: Wave 0 = 전체 기간 중 최저점
        lows_by_price = sorted(lows, key=lambda x: x['price'])
        w0 = lows_by_price[0]
        
        # 2단계: Wave 0 이후의 피벗들만 필터
        after_w0 = [p for p in sorted_pivots if p['date'] > w0['date']]
        highs_after_w0 = [p for p in after_w0 if p['type'] == 'high']
        lows_after_w0 = [p for p in after_w0 if p['type'] == 'low']
        
        if len(highs_after_w0) < 3 or len(lows_after_w0) < 2:
            return self._simple_fallback(w0, sorted_pivots)
        
        # 3단계: Wave 5 = W0 이후 최고점
        highs_by_price = sorted(highs_after_w0, key=lambda x: x['price'], reverse=True)
        w5 = highs_by_price[0]
        
        # 4단계: W0 ~ W5 사이에서 중간 파동 찾기
        between = [p for p in sorted_pivots if w0['date'] < p['date'] < w5['date']]
        highs_between = sorted([p for p in between if p['type'] == 'high'], key=lambda x: x['price'], reverse=True)
        lows_between = sorted([p for p in between if p['type'] == 'low'], key=lambda x: x['price'])
        
        if len(highs_between) < 2 or len(lows_between) < 2:
            return self._simple_fallback(w0, sorted_pivots)
        
        # Wave 1: W0 다음 첫 번째 significant high
        w1 = self._find_first_high_after(w0, highs_between)
        if not w1:
            w1 = highs_between[0] if highs_between else None
        
        # Wave 2: W1 다음 significant low (W0보다 높아야 함)
        if w1:
            lows_after_w1 = [p for p in lows_between if p['date'] > w1['date'] and p['price'] > w0['price']]
            w2 = lows_after_w1[0] if lows_after_w1 else None
        else:
            w2 = None
        
        # Wave 3: W2 다음 significant high (가장 높은 것)
        if w2:
            highs_after_w2 = [p for p in highs_between if p['date'] > w2['date']]
            if highs_after_w2:
                w3 = sorted(highs_after_w2, key=lambda x: x['price'], reverse=True)[0]
            else:
                w3 = None
        else:
            w3 = None
        
        # Wave 4: W3 다음 low (W1보다 높아야 함)
        if w3 and w1:
            lows_after_w3 = [p for p in lows_between if p['date'] > w3['date'] and p['price'] > w1['price']]
            if lows_after_w3:
                w4 = lows_after_w3[0]
            else:
                # W1 위 조건 완화
                lows_after_w3_all = [p for p in between if p['date'] > w3['date'] and p['type'] == 'low']
                w4 = lows_after_w3_all[0] if lows_after_w3_all else None
        else:
            w4 = None
        
        # 검증 및 파동 구성
        waves = []
        if all([w0, w1, w2, w3, w4, w5]):
            # 규칙 검증
            if self._validate_basic_rules(w0, w1, w2, w3, w4, w5):
                waves = [
                    {'label': '0', 'price': w0['price'], 'date': w0['date'], 'type': 'low'},
                    {'label': '1', 'price': w1['price'], 'date': w1['date'], 'type': 'high'},
                    {'label': '2', 'price': w2['price'], 'date': w2['date'], 'type': 'low'},
                    {'label': '3', 'price': w3['price'], 'date': w3['date'], 'type': 'high'},
                    {'label': '4', 'price': w4['price'], 'date': w4['date'], 'type': 'low'},
                    {'label': '5', 'price': w5['price'], 'date': w5['date'], 'type': 'high'},
                ]
        
        if not waves:
            return self._simple_fallback(w0, sorted_pivots)
        
        scenario = WaveScenario(
            waves=waves,
            confidence=0.6,
            reasoning="Algorithmic fallback: Selected waves based on price/time structure (LLM unavailable)",
            rag_sources=[]
        )
        
        return ExpertMessage(
            role='rag_expert',
            content="Fallback scenario created using algorithmic wave detection",
            scenario=scenario,
            questions=["Please validate proportionality and timing"],
            agreed=False
        )
    
    def _find_first_high_after(self, w0: Dict, highs: List[Dict]) -> Optional[Dict]:
        """W0 직후 첫 번째 significant high"""
        for h in sorted(highs, key=lambda x: x['date']):
            if h['date'] > w0['date']:
                return h
        return None
    
    def _validate_basic_rules(self, w0, w1, w2, w3, w4, w5) -> bool:
        """기본 Elliott 규칙 검증"""
        # Rule 1: W2 > W0
        if w2['price'] <= w0['price']:
            return False
        # Rule 2: W3 cannot be shortest
        w1_len = w1['price'] - w0['price']
        w3_len = w3['price'] - w2['price']
        w5_len = w5['price'] - w4['price']
        if w3_len < w1_len and w3_len < w5_len:
            return False
        # Rule 3: W4 > W1
        if w4['price'] < w1['price']:
            return False
        # Date order
        dates = [w0['date'], w1['date'], w2['date'], w3['date'], w4['date'], w5['date']]
        if dates != sorted(dates):
            return False
        return True
    
    def _simple_fallback(self, w0: Dict, sorted_pivots: List[Dict]) -> ExpertMessage:
        """최소한의 fallback"""
        highs = [p for p in sorted_pivots if p['type'] == 'high' and p['date'] > w0['date']]
        if highs:
            w5 = sorted(highs, key=lambda x: x['price'], reverse=True)[0]
            waves = [
                {'label': '0', 'price': w0['price'], 'date': w0['date'], 'type': 'low'},
                {'label': '5', 'price': w5['price'], 'date': w5['date'], 'type': 'high'}
            ]
        else:
            waves = [{'label': '0', 'price': w0['price'], 'date': w0['date'], 'type': 'low'}]
        
        return ExpertMessage(
            role='rag_expert',
            content="Minimal fallback - insufficient data for full wave structure",
            scenario=WaveScenario(waves=waves, confidence=0.3, reasoning="Minimal fallback", rag_sources=[]),
            questions=["Need more data for complete analysis"],
            agreed=False
        )


# === 테스트 ===
if __name__ == "__main__":
    print("=== RAG Expert Test ===\n")
    
    expert = RAGExpert()
    
    if expert.available:
        print("✅ RAG Expert available")
        
        # 테스트 피벗
        test_pivots = [
            {'date': '2022-11-21', 'price': 15599, 'type': 'low'},
            {'date': '2023-06-15', 'price': 24797, 'type': 'low'},
            {'date': '2023-07-13', 'price': 31815, 'type': 'high'},
            {'date': '2024-01-22', 'price': 38505, 'type': 'low'},
            {'date': '2024-03-14', 'price': 73750, 'type': 'high'},
            {'date': '2024-08-05', 'price': 49121, 'type': 'low'},
            {'date': '2025-01-20', 'price': 109115, 'type': 'high'},
        ]
        
        data_summary = {
            'start': '2022-01-01',
            'end': '2025-02-05',
            'atl_price': 15599,
            'atl_date': '2022-11-21',
            'ath_price': 109115,
            'ath_date': '2025-01-20'
        }
        
        result = expert.propose_scenario(
            symbol="BTC-USD",
            data_summary=data_summary,
            available_pivots=test_pivots,
            user_hints={'notes': 'BTC halving cycle analysis'}
        )
        
        print(f"\n=== Proposal ===")
        print(f"Reasoning: {result.content}")
        if result.scenario:
            print(f"Confidence: {result.scenario.confidence:.0%}")
            print(f"Waves:")
            for w in result.scenario.waves:
                print(f"  {w['label']}: ${w['price']:,} ({w['date']})")
    else:
        print("❌ RAG Expert not available")
