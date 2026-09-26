"""Reply decisions use existing intents and states; no separate queue or schema."""
CLASSIFICATION_VERSION = 'reply-triage-1'


def intent_action(intent):
    if intent in ('decline', 'opt_out'):
        return 'stop_contact'
    if intent in ('interested', 'question', 'reading', 'feedback'):
        return 'auto_reply'
    if intent == 'automated':
        return 'ignore_notification'
    return 'human_review'


def handling_label(message):
    """Show actual processing state, not just the model's requested action."""
    if message.get('classification') in ('decline', 'opt_out', 'complaint'):
        return '停止联系 · 不回复'
    if message.get('state') == 'human_review' or message.get('reply_state') in ('held', 'uncertain'):
        return '人工处理'
    if message.get('kind') == 'automated':
        return '自动通知 · 不回复'
    if message.get('state') in ('ignored', 'superseded'):
        return '不回复 · 已停发或被新来信取代'
    if message.get('answered'):
        return '自动回复 · SMTP已接受' if message.get('reply_origin') == 'ai' else '人工回复 · SMTP已接受'
    if intent_action(message.get('classification')) == 'auto_reply':
        return '自动回复 · 待生成或审核'
    return '待判断'
