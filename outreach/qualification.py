"""Profile-fit and contact-permission status carried with source evidence."""
from __future__ import annotations
import json,time

QUALIFICATION_LABELS = {
    'archived': '已归档（须重新核验）',
    'evidence_pending': '证据待核',
    'permission_required': '需记录许可',
    'contactable': '可进入发信流程',
    'excluded': '明确排除',
}
MATCH_LABELS = {
    'matched': '目标匹配',
    'evidence_pending': '证据待核',
    'excluded': '明确排除',
}
REASON_LABELS = {
    'source_restricted': '来源拒绝推广/邮箱采集', 'role_mailbox': '专用角色邮箱',
    'mx_unverified': 'MX未通过', 'email_not_published': '邮箱未逐字发布',
    'email_source_owner_unverified': '官方邮箱来源或任职关系待核',
    'fit_quote_missing': '匹配引文待核', 'identity_unverified': '身份对应待核',
    'location_unverified': '所在地待核', 'country_out_of_scope': '国家不在目标范围',
    'permission_required': '联系许可待记录', 'reverify_required': '旧记录需重新核验',
    'source_snapshot_missing': '有效原文快照缺失', 'source_snapshot_expired': '原文核验过期',
}


def evidence_data(contact):
    try:
        value = json.loads(contact.get('evidence_json') or '{}')
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):value = {}
    match = value.get('profile_match') if isinstance(value.get('profile_match'), dict) else {}
    qualification = value.get('qualification') if isinstance(value.get('qualification'), dict) else {}
    if not qualification:
        qualification = {
            'status': 'excluded' if contact.get('eligibility') == 'blocked' else 'evidence_pending',
            'reasons': [{'code': 'reverify_required', 'message': '此资料尚无新版资格判定；请重新核验来源。'}],
        }
    if not match:
        match = {'status': 'evidence_pending', 'reason': '缺少可追溯的匹配引文核验。'}
    return value, match, qualification


def effective_status(contact, scope='consent_only', now=None, max_age_days=None):
    if contact.get('state')=='archived':return 'archived'
    _, _, qualification = evidence_data(contact)
    status = qualification.get('status', 'evidence_pending')
    if contact.get('eligibility') == 'blocked' or contact.get('state') in ('suppressed', 'deleted'):
        return 'excluded'
    if status == 'contactable':
        if 'active_snapshot_count' in contact and not contact.get('active_snapshot_count'):
            return 'evidence_pending'
        verified_at=contact.get('verified_at')
        if max_age_days is not None and (not verified_at or (time.time() if now is None else now)-verified_at>max_age_days*86400):
            return 'evidence_pending'
        if contact.get('eligibility')=='consent' and (not str(contact.get('permission_note') or '').strip() or str(contact.get('permission_note') or '').startswith('草稿失败：')):
            return 'permission_required'
    if status == 'contactable' and contact.get('eligibility') == 'us_public' and scope != 'us_business_public':
        return 'permission_required'
    return status if status in QUALIFICATION_LABELS else 'evidence_pending'


def with_permission(evidence_json):
    try:
        evidence = json.loads(evidence_json or '{}')
    except (TypeError, ValueError):
        evidence = {}
    qualification = evidence.get('qualification')
    if not isinstance(qualification, dict):
        return json.dumps(evidence, ensure_ascii=False)
    reasons = [r for r in qualification.get('reasons', []) if r.get('code') != 'permission_required']
    qualification['reasons'] = reasons
    qualification['status'] = status_for(reasons)
    evidence['qualification'] = qualification
    evidence['issues'] = [r.get('message','') for r in reasons]
    return json.dumps(evidence, ensure_ascii=False)


def with_human_fit_quote(evidence_json, quote):
    try:
        evidence = json.loads(evidence_json or '{}')
    except (TypeError, ValueError):
        evidence = {}
    match = evidence.get('profile_match')
    qualification = evidence.get('qualification')
    if not isinstance(match, dict) or not isinstance(qualification, dict):
        raise ValueError('缺少新版研究记录；请重新核验来源。')
    reasons = [r for r in qualification.get('reasons', []) if r.get('code') != 'fit_quote_missing']
    match.update(status='matched', quote=quote, reason='管理员在已保存的原文快照中核实了此相关引文。')
    qualification['reasons'] = reasons
    qualification['status'] = status_for(reasons)
    evidence['profile_match'] = match
    evidence['qualification'] = qualification
    evidence['issues'] = [r.get('message','') for r in reasons]
    return json.dumps(evidence, ensure_ascii=False)


def status_for(reasons):
    if any(r.get('code') in ('source_restricted', 'role_mailbox') for r in reasons):
        return 'excluded'
    if any(r.get('code') != 'permission_required' for r in reasons):
        return 'evidence_pending'
    if reasons:
        return 'permission_required'
    return 'contactable'


def view_reasons(contact, qualification, status, max_age_days=None, now=None):
    reasons=list(qualification.get('reasons', []))
    if status=='evidence_pending' and qualification.get('status')=='contactable':
        if 'active_snapshot_count' in contact and not contact.get('active_snapshot_count'):
            reasons.append({'code':'source_snapshot_missing','message':'没有有效的原文快照；请重新核验来源。'})
        elif max_age_days is not None:
            reasons.append({'code':'source_snapshot_expired','message':'原文核验已过期；请重新核验来源。'})
    elif status=='permission_required' and not any(r.get('code')=='permission_required' for r in reasons):
        reasons.append({'code':'permission_required','message':'当前联系范围需要单独记录许可。'})
    return reasons


def summary(contacts, scope='consent_only', max_age_days=None, now=None):
    counts = {key: 0 for key in ('target_match', 'evidence_pending', 'permission_required', 'contactable', 'excluded', 'archived')}
    overlaps = {}
    for contact in contacts:
        if contact.get('state') == 'deleted' or contact.get('historical'):
            continue
        _, match, qualification = evidence_data(contact)
        status = effective_status(contact, scope, now, max_age_days)
        counts[status] = counts.get(status, 0) + 1
        if status=='archived':continue
        if match.get('status') == 'matched' and status != 'excluded':
            counts['target_match'] += 1
        for reason in view_reasons(contact, qualification, status, max_age_days, now):
            code = reason.get('code', 'other')
            overlaps[code] = overlaps.get(code, {'label':REASON_LABELS.get(code,reason.get('message',code)),'count':0})
            overlaps[code]['count'] += 1
    return {'counts': counts, 'overlapping_reasons': list(overlaps.values())}


def annotate(contact, scope='consent_only', max_age_days=None, now=None):
    _, match, qualification = evidence_data(contact)
    contact['profile_match_status'] = match.get('status', 'evidence_pending')
    contact['profile_match_label'] = MATCH_LABELS.get(contact['profile_match_status'], '证据待核')
    contact['profile_match_reason'] = match.get('reason', '')
    contact['qualification_status'] = effective_status(contact, scope, now, max_age_days)
    contact['qualification_label'] = QUALIFICATION_LABELS[contact['qualification_status']]
    contact['qualification_reasons'] = view_reasons(contact, qualification, contact['qualification_status'], max_age_days, now)
    return contact
