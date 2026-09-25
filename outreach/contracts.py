"""Generation contract 3: model owns prose, program owns recipients and framing."""
import re,json
from .domain import BOOK_TITLE,BOOK_SUBTITLE,AUTHOR,BOOK_URL,CHAPTERS,validate_initial,policy_text_guard,safe_header,sensitive_request
from .profiles import digest
COPY_FIELDS={'subject','body','recipient_claims','book_fact_ids','selected_chapter_ids','offered_next_step','asset_id','asset_version'}
CONTRACT=3
POLICY_VERSION='1.3-1'
BOOK_FACTS={'title':BOOK_TITLE,'subtitle':BOOK_SUBTITLE,'author':AUTHOR,'publication':'Published on Amazon',
 'method':'Plan with one AI; use its written brief to direct other AIs to build and check. Humans keep important decisions.',
 'limits':'Practical exercises, not guaranteed results, a children’s curriculum or evidence of customer outcomes.',
 'chapters':CHAPTERS}
BOOK_VERSION=digest(BOOK_FACTS)

def validate_copy(value,source_rows,assets=(),initial=True):
    if not isinstance(value,dict):raise ValueError('Draft must be an object')
    allowed=COPY_FIELDS
    if set(value)-allowed:raise ValueError('Unknown draft fields; recipient/tools not allowed')
    subject=safe_header(value.get('subject'),240);body=value.get('body')
    if not isinstance(body,str) or not 20<=len(body.split())<=(120 if initial else 220):raise ValueError('Invalid core body word count')
    policy_text_guard(subject,initial=initial);policy_text_guard(body,initial=initial)
    if sensitive_request(body) or re.search(r'(?:send|share|provide|attach).{0,50}(?:full|whole|entire|complete).{0,20}(?:book|chapter)|(?:send|share|provide|attach).{0,25}(?:PDF|EPUB|chapter file|chapter text)',body,re.I):raise ValueError('Unsafe commitment/instruction')
    if initial:
        validate_initial(body)
        if subject.lower().startswith(('re:','fw:','fwd:')):raise ValueError('False reply subject')
    if re.search(r'(?im)^\s*(?:hi |dear |best,|regards,|to stop these messages|book promotion /)',body):raise ValueError('Model must not add greeting/signature/footer')
    if re.search(r'www\.|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:https?://|mailto:)',body,re.I) and initial:raise ValueError('No links or addresses in initial prose')
    facts=value.get('book_fact_ids');chapters=value.get('selected_chapter_ids');claims=value.get('recipient_claims')
    if not isinstance(facts,list) or not facts or any(x not in BOOK_FACTS for x in facts):raise ValueError('Unknown book fact')
    if not isinstance(chapters,list) or any(type(x) is not int or x not in CHAPTERS for x in chapters):raise ValueError('Unknown chapter')
    if not isinstance(claims,list) or len(claims)>8:raise ValueError('Invalid claims')
    lookup={r['id']:r for r in source_rows}
    for claim in claims:
        if not isinstance(claim,dict) or not isinstance(claim.get('statement'),str):raise ValueError('Invalid claim')
        r=lookup.get(claim.get('source_id'));quote=claim.get('quote')
        if not r or not isinstance(quote,str) or len(quote)<12 or quote not in r['text']:raise ValueError('Unsupported claim reference')
    if initial and not claims:raise ValueError('Initial needs evidence-grounded relevance')
    if value.get('offered_next_step') not in ('chapter_recommendation','discuss_application','example','none'):raise ValueError('Unknown next step')
    if value.get('offered_next_step')=='example' or value.get('asset_id') is not None:
        asset=next((a for a in assets if a['id']==value.get('asset_id') and a['version']==value.get('asset_version')),None)
        if not asset or not asset['approved'] or digest(asset['body'])!=asset['content_hash']:raise ValueError('Missing approved example/version')
    elif re.search(r'(?:send|share|show|offer|provide).{0,50}(?:example|sample|demo)|(?:would|can|may|shall|want|like).{0,45}(?:example|sample|demo)|(?:example|sample|demo).{0,25}(?:useful|helpful|interested)',body,re.I):raise ValueError('Unbacked example promise')
    return dict(value,subject=subject,body=body)

def framed(contact,body):
    return f"Hi {safe_header(contact['name'].split()[0],80)},\n\n{body}\n\nBest,\n{AUTHOR}"

def review_result(result):
    if not isinstance(result,dict) or type(result.get('approved')) is not bool:raise ValueError('Review requires boolean verdict')
    if not isinstance(result.get('hard_failures'),list) or any(not isinstance(x,str) for x in result['hard_failures']):raise ValueError('Review requires hard failures')
    if result['approved'] and result['hard_failures']:raise ValueError('Conflicting review')
    quality=result.get('quality')
    if not isinstance(quality,dict) or any(type(quality.get(k)) not in (int,float) or not 0<=quality[k]<=5 for k in ('relevance','specificity','naturalness','reply_burden')):raise ValueError('Invalid quality assessment')
    if not isinstance(result.get('reason'),str):raise ValueError('Missing review reason')
    return {'approved':result['approved'],'hard_failures':[x[:300] for x in result['hard_failures'][:8]],'reason':result['reason'][:600],'quality':{k:quality[k] for k in ('relevance','specificity','naturalness','reply_burden')}}
