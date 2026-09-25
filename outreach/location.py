"""Conservative source-text US location evidence, not geocoding or permission.

Recognizes explicit US assertions or city+state strings on the owner's site.
An ambiguous city alone never resolves a country. Contexts referring to clients,
past residences, travel, negation, or conflicting locations stay in review.
"""
from __future__ import annotations

import re

SOURCE_VERIFICATION_VERSION = 3
STATES = {
    'AL':'Alabama', 'AK':'Alaska', 'AZ':'Arizona', 'AR':'Arkansas', 'CA':'California',
    'CO':'Colorado', 'CT':'Connecticut', 'DE':'Delaware', 'DC':'District of Columbia',
    'FL':'Florida', 'GA':'Georgia', 'HI':'Hawaii', 'ID':'Idaho', 'IL':'Illinois',
    'IN':'Indiana', 'IA':'Iowa', 'KS':'Kansas', 'KY':'Kentucky', 'LA':'Louisiana',
    'ME':'Maine', 'MD':'Maryland', 'MA':'Massachusetts', 'MI':'Michigan',
    'MN':'Minnesota', 'MS':'Mississippi', 'MO':'Missouri', 'MT':'Montana',
    'NE':'Nebraska', 'NV':'Nevada', 'NH':'New Hampshire', 'NJ':'New Jersey',
    'NM':'New Mexico', 'NY':'New York', 'NC':'North Carolina', 'ND':'North Dakota',
    'OH':'Ohio', 'OK':'Oklahoma', 'OR':'Oregon', 'PA':'Pennsylvania',
    'RI':'Rhode Island', 'SC':'South Carolina', 'SD':'South Dakota',
    'TN':'Tennessee', 'TX':'Texas', 'UT':'Utah', 'VT':'Vermont', 'VA':'Virginia',
    'WA':'Washington', 'WV':'West Virginia', 'WI':'Wisconsin', 'WY':'Wyoming',
}
# State names/abbreviations: USPS Publication28 AppendixB. This is not a city registry.
CITY = r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'’\-]*(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'’\-]*){0,5}"
STATE_NAMES = '|'.join(re.escape(v) for v in sorted(STATES.values(), key=len, reverse=True))
CITY_STATE = re.compile(r'\b(' + CITY + r'),\s*(?:' + '|'.join(STATES) + r'|(?i:' + STATE_NAMES + r'))\b')
STATE_ZIP = re.compile(r'\b(?:' + '|'.join(STATES) + r')\s+\d{5}(?:-\d{4})?\b')
US = r'(?:United States(?: of America)?|USA|U\.S\.A\.?|US|U\.S\.?)'
EXPLICIT_US = re.compile(r'\b(?:based|located|headquartered)\s+in\s+(?:the\s+)?' + US + r'(?!\w)|\b' + US + r'[-\s]based\b', re.I)
# False positives are held, not corrected by a model. Keep the reason visible to the operator.
NOT_OWNER = re.compile(
    r"\b(?:not|never|no longer|formerly|previously|born|grew up|moved from|moving from|"
    r"moving to|relocat(?:ed|ing) from|used to|clients?|customers?|serv(?:ing|es|ice)|"
    r"visiting|visited|travel|conferences?|workshops?|events?|testimonials?|case stud(?:y|ies))\b", re.I)
FOREIGN = re.compile(r'\b(?:Canada|Canadian|Toronto|Ontario|United Kingdom|UK|London|Australia|Australian|'
                     r'Germany|German|France|French|Netherlands|Ireland|New Zealand|India|Singapore|Hong Kong)\b', re.I)
# These state-looking combinations can name a foreign city/country or state.
# Hold ambiguity instead of treating a syntactic state match as a US geocode.
AMBIGUOUS_CITY_STATE = re.compile(
    r'\b(?:(?:Tbilisi|Batumi|Kutaisi)\s*,\s*(?:Georgia|GA)|Perth\s*,\s*(?:WA|Washington))\b', re.I)
FOREIGN_LOCATION = re.compile(r'\b(?:based|located|headquartered|live|living|work(?:ing)?)\s+(?:in|from)\s+[^.!?;]{0,90}', re.I)


def normalize_space(value: str) -> str:
    return ' '.join(str(value).split())


def evaluate_us_location(quote: str, page_texts: list[str]) -> dict:
    """Return evidence detail; a caller still checks scope, email, owner and permission."""
    quote = normalize_space(quote)
    result = {'status':'review', 'rule':'', 'quote':quote[:500], 'reason':''}
    if not 3 <= len(quote) <= 500:
        result['reason'] = '地点摘录缺失或过长'
        return result
    pages = [normalize_space(p) for p in page_texts]
    contexts = []
    for page in pages:
        for match in re.finditer(re.escape(quote), page, re.I):
            # Check the surrounding sentence; a model cannot crop "clients in" out of evidence.
            start = max(page.rfind(mark, 0, match.start()) for mark in ('. ', '; ', '! ', '? ', '\n'))
            left = max(start + 2 if start >= 0 else 0, match.start() - 140)
            right = min(len(page), match.end() + 90)
            if quote.rstrip().endswith(('.', ';', '!', '?')):
                right = match.end()
            else:
                tails = [page.find(mark, match.end()) for mark in ('. ', '; ', '! ', '? ')]
                ends = [v + 1 for v in tails if v >= 0]
                if ends:
                    right = min(right, min(ends))
            contexts.append(page[left:right])
    if not contexts:
        result['reason'] = '地点摘录未逐字出现在单个来源页面中'
        return result
    if NOT_OWNER.search(quote) or any(NOT_OWNER.search(text) for text in contexts):
        result['reason'] = '地点上下文可能是客户/历史/活动/否定地点，保留人工核实'
        return result
    if (FOREIGN.search(quote) or AMBIGUOUS_CITY_STATE.search(quote)
            or any(FOREIGN.search(text) or AMBIGUOUS_CITY_STATE.search(text) for text in contexts)):
        result['reason'] = '地点上下文含国外或冲突线索，不自动推断美国所在地'
        return result
    for page in pages:
        if any(FOREIGN.search(m.group()) for m in FOREIGN_LOCATION.finditer(page)):
            result['reason'] = '同一来源包含其他所在地声明，需要人工核实'
            return result
    if EXPLICIT_US.search(quote):
        rule = 'explicit_us'
    elif CITY_STATE.search(quote):
        rule = 'city_state'
    elif STATE_ZIP.search(quote):
        rule = 'state_zip'
    else:
        result['reason'] = '缺少美国国家声明或城市+州证据；不从城市名猜国家'
        return result
    result.update(status='supported_us', rule=rule,
                  reason='来源文本支持美国所在地；不证明身份、居民身份、业务归属或营销许可')
    return result
