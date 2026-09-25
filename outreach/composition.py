"""Source-grounded, concise invitation composition.

The model selects an exact source quote/topic and a natural wording pattern.
The program owns the final wording boundaries, book claims and recipients.
This avoids upgrading a copied quote into an unverified achievement or claim
that the author personally read/liked a recipient's work.
"""
from __future__ import annotations
import re
from .domain import (AUTHOR, BOOK_TITLE, BOOK_SUBTITLE, PERSONAS, safe_header,
                     policy_text_guard, sensitive_request, validate_initial)

OPENINGS = {
    'focus': 'Your site mentions “{quote}”, which relates to this book’s practical AI exercises.',
    'work': 'Your site describes work involving “{quote}”.',
    'connection': 'The phrase “{quote}” on your site connects with a question this book explores.',
}
SUBJECTS = {
    'exercise': 'A practical AI exercise for {topic}',
    'question': 'A question about {topic} and AI',
    'project': 'Keeping human decisions in {topic}',
}
BENEFITS = {
    'operator': 'helps turn a practical need into a small usable tool while keeping scope and acceptance yours.',
    'creator': 'supports drafting and revision while keeping the theme, creative choices, and final decisions yours.',
    'knowledge': 'connects scattered source materials to a checkable deliverable, keeping evidence separate from approval.',
}


def _literal_slot(value, source, *, label, min_words, max_words, max_chars):
    if not isinstance(value, str):
        raise ValueError(label + ' must be text')
    if any(ord(c) < 32 for c in value) or len(value) > max_chars:
        raise ValueError(label + ' contains control characters or is too long')
    if value != value.strip() or not min_words <= len(value.split()) <= max_words:
        raise ValueError(label + ' length outside allowed bounds')
    if value not in source:
        raise ValueError(label + ' is not an exact substring of the verified excerpt')
    policy_text_guard(value, initial=True)
    if sensitive_request(value) or re.search(r'www\.|\b[A-Za-z0-9.-]+\.(?:com|org|net|io|co)\b|@|[<>]', value, re.I):
        raise ValueError(label + ' contains a link, address or instruction')
    return value


def validate_copy_slots(contact, result):
    """No new facts may live in a model-supplied free-form subject/opening."""
    excerpt = str(contact.get('fit_excerpt', ''))
    if not isinstance(result, dict):
        raise ValueError('personalization must be an object')
    quote = _literal_slot(result.get('quote'), excerpt, label='quote', min_words=3, max_words=16, max_chars=160)
    topic = _literal_slot(result.get('topic'), excerpt, label='topic', min_words=1, max_words=7, max_chars=50)
    opening_style = next((key for key, pattern in OPENINGS.items()
                          if result.get('opening_style') in (key, pattern.format(quote=quote))), None)
    subject_style = next((key for key, pattern in SUBJECTS.items()
                          if result.get('subject_style') in (key, pattern.format(topic=topic))), None)
    if opening_style is None or subject_style is None:
        raise ValueError('Unknown wording pattern')
    subject = safe_header(SUBJECTS[subject_style].format(topic=topic), 100)
    opening = OPENINGS[opening_style].format(quote=quote)
    policy_text_guard(subject, initial=True)
    policy_text_guard(opening, initial=True)
    return {'subject':subject, 'opening':opening, 'quote':quote, 'topic':topic,
            'opening_style':opening_style, 'subject_style':subject_style,
            'copy_version':2, 'source_url':contact.get('profile_url') or contact.get('source_url','')}


def consent_copy(contact):
    """No source-based claims when only actual contact permission is available."""
    if contact.get('eligibility') != 'consent':
        raise ValueError('No verified source and no recorded consent')
    topic = {'operator':'a practical tool', 'creator':'a creative project', 'knowledge':'a work deliverable'}.get(contact.get('persona'), 'your project')
    return {'subject':f'A human-led AI exercise for {topic}',
            'opening':'I’m reaching out with a practical AI reading invitation.',
            'quote':'','topic':'','copy_version':2,'source_url':'','basis':'documented consent; no source claim'}


def render_initial(contact, copy):
    persona = contact.get('persona', 'operator')
    if persona not in PERSONAS:
        raise ValueError('Unknown reader persona')
    first_name = safe_header(contact['name'].split()[0], 80)
    body = (
        f"Hi {first_name},\n\n{copy['opening']}\n\n"
        f"I’m {AUTHOR}, author of {BOOK_TITLE}: {BOOK_SUBTITLE}, published on Amazon.\n\n"
        f"The method—Think → Write → Build → Check—{BENEFITS[persona]}\n\n"
        "Would a chapter recommendation be useful? I'd welcome private thoughts on what works and what remains unclear.\n\n"
        "Existing Kindle Unlimited members can check access on Amazon. There’s no obligation to buy or post a review.\n\n"
        f"Best,\n{AUTHOR}"
    )
    validate_initial(body)
    return body
