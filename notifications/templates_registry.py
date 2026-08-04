"""Registry mapping template names to their subject + body templates.

Adding a new email type = one entry here + the two template files. The engine
(service.send_email) and any feature call sites reference templates by name only.
"""
from django.template.loader import render_to_string


class UnknownTemplate(Exception):
    pass


# name -> {subject, html, text}
TEMPLATES = {
    'verification_code': {
        'subject': 'Your Jokes For verification code',
        'html': 'notifications/email/verification_code.html',
        'text': 'notifications/email/verification_code.txt',
    },
    'daily_digest': {
        'subject': "Today's joke is ready",
        'html': 'notifications/email/daily_digest.html',
        'text': 'notifications/email/daily_digest.txt',
    },
    'creator_milestone': {
        'subject': 'Your jokes made people laugh',
        'html': 'notifications/email/creator_milestone.html',
        'text': 'notifications/email/creator_milestone.txt',
    },
}


def render_template(template_name, context):
    """Return (subject, html_body, text_body) for a registered template."""
    entry = TEMPLATES.get(template_name)
    if entry is None:
        raise UnknownTemplate(f"No registered email template '{template_name}'.")
    subject = entry['subject']
    html_body = render_to_string(entry['html'], context)
    text_body = render_to_string(entry['text'], context)
    return subject, html_body, text_body
