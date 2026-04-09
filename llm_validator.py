"""
LLM Wave Validator - Elliott Wave 검증 및 교정
==============================================
알고리즘 결과를 LLM으로 검증하고 필요시 교정
"""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from .llm_utils import safe_parse_json

_logger = logging.getLogger(__name__)

# LLM 클라이언트
try:
    from knowledge_core.gemini_client import GeminiClient, GeminiModel
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
class LLMUsageTracker:
    """LLM 호출 토큰/비용 추적"""
    total_tokens: int = 0
    total_cost_estimate: float = 0.0
    call_count: int = 0
    _history: List[Dict] = field(default_factory=list)

    # 모델별 1K 토큰 예상 비용 (USD)
    COST_PER_1K = {
        "gemini-flash": 0.0001,
        "gemini-pro": 0.0005,
        "default": 0.0003,
    }

    def record(self, model: str, tokens: int) -> None:
        """호출 기록 추가"""
        rate = self.COST_PER_1K.get(model, self.COST_PER_1K["default"])
        cost = (tokens / 1000) * rate
        self.total_tokens += tokens
        self.total_cost_estimate += cost
        self.call_count += 1
        self._history.append({
            "model": model,
            "tokens": tokens,
            "cost": cost,
            "timestamp": datetime.now().isoformat(),
        })

    def summary(self) -> str:
        """사용량 요약 문자열"""
        return (
            f"LLM Usage: {self.call_count} calls, "
            f"{self.total_tokens:,} tokens, "
            f"${self.total_cost_estimate:.4f} est. cost"
        )


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool
    confidence: float
    corrections: List[Dict]
    reasoning: str
    llm_used: bool


@dataclass 
class CycleEstimate:
    """사이클 기간 추정 결과"""
    cycle_months: int
    confidence: float
    reasoning: str
    llm_used: bool


class LLMWaveValidator:
    """
    LLM 기반 Elliott Wave 검증기
    
    기능:
    1. 사이클 기간 추정 (자산별 특성 반영)
    2. 파동 구조 검증 (Elliott Wave 규칙)
    3. 파동 교정 제안 (문제 발견 시)
    """
    
    def __init__(self, enable_rag: bool = True):
        # LLM 초기화
        if LLM_AVAILABLE:
            self.llm = GeminiClient()
            if not self.llm.available:
                self.llm = None
        else:
            self.llm = None
        
        # RAG 초기화
        if enable_rag and RAG_AVAILABLE:
            try:
                self.rag = RAGRetriever()
                if not self.rag.available:
                    self.rag = None
            except (ImportError, OSError, RuntimeError) as e:
                _logger.warning("RAG initialization failed: %s", e)
                self.rag = None
        else:
            self.rag = None

        self.available = self.llm is not None
        self.usage = LLMUsageTracker()
    
    def estimate_cycle_duration(
        self,
        symbol: str,
        atl_price: float,
        atl_date: datetime,
        ath_price: float,
        ath_date: datetime,
        data_start: datetime,
        data_end: datetime
    ) -> CycleEstimate:
        """
        LLM으로 자산별 사이클 기간 추정
        
        Args:
            symbol: 자산 심볼 (BTC-USD, ETH-USD, AAPL 등)
            atl_price: ATL 가격
            atl_date: ATL 날짜
            ath_price: ATH 가격
            ath_date: ATH 날짜
            data_start: 데이터 시작일
            data_end: 데이터 종료일
        
        Returns:
            CycleEstimate: 사이클 기간 추정 결과
        """
        if not self.llm:
            # 폴백: 자산 유형 기반 기본값
            return self._fallback_cycle_estimate(symbol)
        
        # RAG 지식 검색
        rag_context = ""
        if self.rag:
            result = self.rag.search(f"{symbol} market cycle duration halving", top_k=3)
            if result['available']:
                rag_context = result['summary']
        
        prompt = f"""You are an expert in market cycles and Elliott Wave theory.

**Asset:** {symbol}
**Data Period:** {data_start.strftime('%Y-%m-%d')} to {data_end.strftime('%Y-%m-%d')}
**ATL:** ${atl_price:,.0f} on {atl_date.strftime('%Y-%m-%d')}
**ATH:** ${ath_price:,.0f} on {ath_date.strftime('%Y-%m-%d')}

**Reference Knowledge:**
{rag_context if rag_context else "Use your knowledge of market cycles."}

**Task:**
Estimate the typical full market cycle duration (in months) for this asset from trough to peak.

Consider:
- BTC: ~48 months (4-year halving cycle)
- ETH: Similar to BTC but can vary
- Stocks: 7-10 year economic cycles, or sector-specific
- Indices: Economic cycle dependent

**Output JSON only:**
{{"cycle_months": <number>, "confidence": <0.0-1.0>, "reasoning": "<brief explanation>"}}"""

        try:
            response = self.llm.generate(
                prompt, 
                model=GeminiModel.FLASH_20,  # 비용 효율적
                temperature=0.3,
                max_tokens=300
            )
            
            # JSON 파싱
            result = self._parse_json(response)

            # 토큰 추적 (응답 길이 기반 추정)
            est_tokens = len(prompt.split()) + len(response.split())
            self.usage.record("gemini-flash", est_tokens)

            # 응답 검증
            if not self._validate_llm_response(
                result,
                required_fields=["cycle_months", "confidence"],
                ranges={"cycle_months": (1, 240), "confidence": (0.0, 1.0)},
            ):
                _logger.warning("LLM cycle response failed validation, using fallback")
                return self._fallback_cycle_estimate(symbol)

            return CycleEstimate(
                cycle_months=result.get('cycle_months', 27),
                confidence=result.get('confidence', 0.5),
                reasoning=result.get('reasoning', 'LLM estimation'),
                llm_used=True
            )
        except Exception as e:
            _logger.warning("LLM cycle estimation failed: %s", e)
            return self._fallback_cycle_estimate(symbol)
    
    def validate_wave_structure(
        self,
        waves: List[Dict],
        symbol: str,
        timeframe: str = "1d",
        available_pivots: Optional[List[Dict]] = None
    ) -> ValidationResult:
        """
        LLM으로 파동 구조 검증
        
        Args:
            waves: 감지된 파동 리스트
                [{'label': '0', 'price': 15599, 'date': '2022-11-21', 'type': 'low'}, ...]
            symbol: 자산 심볼
            timeframe: 타임프레임
            available_pivots: 교정에 사용 가능한 피벗 포인트 리스트 (옵션)
                [{'date': '2023-06-15', 'price': 24797, 'type': 'low'}, ...]
        
        Returns:
            ValidationResult: 검증 결과
        """
        if not self.llm:
            return ValidationResult(
                is_valid=True,
                confidence=0.5,
                corrections=[],
                reasoning="LLM unavailable - algorithmic result accepted",
                llm_used=False
            )
        
        # RAG 지식 검색
        rag_rules = ""
        if self.rag:
            result = self.rag.search("Elliott Wave impulse rules violations", top_k=3)
            if result['available']:
                rag_rules = result['summary']
        
        # 파동 정보 포맷팅
        wave_text = self._format_waves_for_prompt(waves)
        
        # 사용 가능한 피벗 포인트 포맷팅
        pivot_text = ""
        if available_pivots:
            pivot_lines = []
            for p in available_pivots:
                pivot_lines.append(f"- {p['date']}: ${p['price']:,.0f} ({p['type']})")
            pivot_text = "\n".join(pivot_lines)
        
        prompt = f"""You are an Elliott Wave expert. Validate this wave structure.

**Asset:** {symbol}
**Timeframe:** {timeframe}

**Detected Waves:**
{wave_text}

**Elliott Wave Rules (must all pass):**
{rag_rules if rag_rules else '''
1. Wave 2 cannot retrace more than 100% of Wave 1
2. Wave 3 cannot be the shortest among waves 1, 3, and 5
3. Wave 4 cannot overlap with Wave 1's price territory
4. Wave 5 must exceed Wave 3's end (in impulse)
5. Waves alternate: if Wave 2 is sharp, Wave 4 should be sideways
'''}

{f'''**Available Alternative Pivot Points (for corrections):**
{pivot_text}

⚠️ IMPORTANT: If you suggest corrections, you MUST select prices ONLY from the list above.
Do NOT suggest arbitrary prices that are not in this list.
''' if pivot_text else ''}

**Task:**
1. Check each rule
2. If violations found, suggest corrections using ONLY the available pivot points above
3. Assess overall validity

**Output JSON only:**
{{
  "is_valid": <true/false>,
  "confidence": <0.0-1.0>,
  "violations": ["<violation1>", ...],
  "corrections": [
    {{"wave": "<label>", "current_price": <num>, "suggested_price": <NUM_FROM_ABOVE_LIST>, "suggested_date": "<DATE_FROM_ABOVE_LIST>", "reason": "<why>"}}
  ],
  "reasoning": "<brief assessment>"
}}"""

        try:
            response = self.llm.generate(
                prompt,
                model=GeminiModel.FLASH_20,
                temperature=0.2,
                max_tokens=600
            )

            result = self._parse_json(response)

            # 토큰 추적
            est_tokens = len(prompt.split()) + len(response.split())
            self.usage.record("gemini-flash", est_tokens)

            # 응답 검증
            if not self._validate_llm_response(
                result,
                required_fields=["is_valid", "confidence"],
                ranges={"confidence": (0.0, 1.0)},
            ):
                _logger.warning("LLM validation response failed field check")
                return ValidationResult(
                    is_valid=True,
                    confidence=0.5,
                    corrections=[],
                    reasoning="LLM response validation failed",
                    llm_used=False,
                )

            return ValidationResult(
                is_valid=result.get('is_valid', True),
                confidence=result.get('confidence', 0.5),
                corrections=result.get('corrections', []),
                reasoning=result.get('reasoning', 'LLM validation'),
                llm_used=True
            )
        except Exception as e:
            _logger.warning("LLM validation failed: %s", e)
            return ValidationResult(
                is_valid=True,
                confidence=0.5,
                corrections=[],
                reasoning=f"LLM error: {e}",
                llm_used=False
            )
    
    def _format_waves_for_prompt(self, waves: List[Dict]) -> str:
        """파동 정보를 프롬프트용 텍스트로 변환"""
        lines = []
        for w in waves:
            label = w.get('label', '?')
            price = w.get('price', 0)
            date = w.get('date', 'unknown')
            wtype = w.get('type', 'unknown')
            lines.append(f"Wave {label}: ${price:,.0f} ({date}) - {wtype}")
        return "\n".join(lines)
    
    def _parse_json(self, response: str) -> Dict:
        """LLM 응답에서 JSON 추출 (safe_parse_json 위임)"""
        result, ok = safe_parse_json(response, fallback={})
        if not ok:
            raise json.JSONDecodeError("Failed to parse LLM response", response, 0)
        return result

    def _validate_llm_response(
        self,
        data: Dict,
        required_fields: List[str],
        ranges: Optional[Dict[str, tuple]] = None,
    ) -> bool:
        """
        LLM 응답 필드/범위 검증

        Args:
            data: 파싱된 LLM 응답 딕셔너리
            required_fields: 필수 키 목록
            ranges: 키별 (min, max) 범위 검증 (선택)

        Returns:
            True if valid
        """
        for f in required_fields:
            if f not in data:
                _logger.warning("LLM response missing required field: %s", f)
                return False
        if ranges:
            for key, (lo, hi) in ranges.items():
                val = data.get(key)
                if val is not None and isinstance(val, (int, float)):
                    if val < lo or val > hi:
                        _logger.warning(
                            "LLM response field '%s' = %s out of range [%s, %s]",
                            key, val, lo, hi,
                        )
                        return False
        return True

    def _fallback_cycle_estimate(self, symbol: str) -> CycleEstimate:
        """LLM 없을 때 자산 유형 기반 폴백"""
        symbol_upper = symbol.upper()
        
        # 암호화폐
        if 'BTC' in symbol_upper or 'BITCOIN' in symbol_upper:
            return CycleEstimate(27, 0.8, "BTC 4-year halving cycle (peak ~27 months from ATL)", False)
        if 'ETH' in symbol_upper or 'ETHEREUM' in symbol_upper:
            return CycleEstimate(24, 0.7, "ETH follows BTC but can peak earlier", False)
        if any(x in symbol_upper for x in ['CRYPTO', 'COIN', 'USDT']):
            return CycleEstimate(24, 0.6, "Crypto follows BTC cycle", False)
        
        # 주식 지수
        if any(x in symbol_upper for x in ['SPY', 'SPX', 'QQQ', 'NDX', 'DJI']):
            return CycleEstimate(48, 0.6, "US equity cycles ~4 years", False)
        
        # 개별 주식
        if any(x in symbol_upper for x in ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']):
            return CycleEstimate(36, 0.5, "Tech stock cycles vary", False)
        
        # 기본값
        return CycleEstimate(36, 0.4, "Default estimation", False)


# === 테스트 ===
if __name__ == "__main__":
    print("=== LLM Wave Validator Test ===\n")
    
    validator = LLMWaveValidator()
    
    if validator.available:
        print("✅ LLM Validator available")
        
        # 사이클 추정 테스트
        print("\n--- Cycle Estimation ---")
        estimate = validator.estimate_cycle_duration(
            symbol="BTC-USD",
            atl_price=15599,
            atl_date=datetime(2022, 11, 21),
            ath_price=109115,
            ath_date=datetime(2025, 1, 20),
            data_start=datetime(2022, 1, 1),
            data_end=datetime(2025, 2, 5)
        )
        print(f"Cycle: {estimate.cycle_months} months")
        print(f"Confidence: {estimate.confidence:.0%}")
        print(f"Reasoning: {estimate.reasoning}")
        print(f"LLM used: {estimate.llm_used}")
        
        # 파동 검증 테스트
        print("\n--- Wave Validation ---")
        test_waves = [
            {'label': '0', 'price': 15599, 'date': '2022-11-21', 'type': 'low'},
            {'label': '1', 'price': 31815, 'date': '2023-07-13', 'type': 'high'},
            {'label': '2', 'price': 24797, 'date': '2023-06-15', 'type': 'low'},
            {'label': '3', 'price': 73750, 'date': '2024-03-14', 'type': 'high'},
            {'label': '4', 'price': 49121, 'date': '2024-08-05', 'type': 'low'},
            {'label': '5', 'price': 109115, 'date': '2025-01-20', 'type': 'high'},
        ]
        
        validation = validator.validate_wave_structure(test_waves, "BTC-USD")
        print(f"Valid: {validation.is_valid}")
        print(f"Confidence: {validation.confidence:.0%}")
        print(f"Reasoning: {validation.reasoning}")
        if validation.corrections:
            print(f"Corrections: {validation.corrections}")
    else:
        print("❌ LLM not available")
        
        # 폴백 테스트
        print("\n--- Fallback Test ---")
        estimate = validator._fallback_cycle_estimate("BTC-USD")
        print(f"BTC cycle: {estimate.cycle_months} months")
