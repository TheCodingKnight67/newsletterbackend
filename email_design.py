"""Validated design tokens rendered into email-compatible inline styles."""
import html
import json
import re
from urllib.parse import urlsplit

DEFAULT = {'background': '#eef2ff', 'card': '#ffffff', 'text': '#232946', 'accent': '#6956b8', 'font': 'serif'}
FONTS = {'serif': 'Georgia, Times New Roman, serif', 'sans': 'Arial, Helvetica, sans-serif',
         'mono': 'Courier New, Courier, monospace'}


def luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


def readable_text(background, preferred=None):
    light = luminance(background)
    if preferred:
        other = luminance(preferred)
        if (max(light, other) + 0.05) / (min(light, other) + 0.05) >= 4.5:
            return preferred
    return '#ffffff' if (light + 0.05) / 0.05 < 1.05 / (light + 0.05) else '#000000'


def default_theme(payload):
    identity = (payload.get('character_name', '') + ' ' + payload.get('character_series', '')).casefold()
    if 'gojo' in identity:
        return dict(DEFAULT, background='#080f20', card='#f5faff', text='#152640', accent='#42baff', font='sans')
    if 'vox' in identity:
        return dict(DEFAULT, background='#081b26', card='#102b38', text='#e4fcff', accent='#22d5e8', font='mono')
    if 'tanjiro' in identity:
        return dict(DEFAULT, background='#102820', card='#f7f3e8', text='#18392d', accent='#2a8c66', font='serif')
    return dict(DEFAULT)


def normalize_theme(raw, payload):
    theme = default_theme(payload)
    if isinstance(raw, dict):
        for key in ('background', 'card', 'text', 'accent'):
            value = raw.get(key)
            if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                theme[key] = value.lower()
        if isinstance(raw.get('font'), str) and raw['font'] in FONTS:
            theme['font'] = raw['font']
    theme['text'] = readable_text(theme['card'], theme['text'])
    return theme


def stored_theme(db, job):
    import models
    design = db.get(models.EmailDesign, job.id)
    return json.loads(design.theme) if design else None


def render_email(job, unsubscribe_url=None, theme=None):
    payload = json.loads(job.payload)
    palette = normalize_theme(theme, payload)
    bg, card, ink, accent = (palette[key] for key in ('background', 'card', 'text', 'accent'))
    accent_ink = readable_text(accent)
    font = FONTS[palette['font']]
    escape = html.escape
    name = escape(payload.get('character_name', 'Your character'))
    series = escape(payload.get('character_series', ''))
    subject = escape(job.subject or 'A message for you')
    paragraphs = ''.join('<p style="margin:0 0 20px;font-size:17px;line-height:1.75;overflow-wrap:anywhere">' + escape(p).replace('\n', '<br>') + '</p>'
                         for p in re.split(r'\n\s*\n', job.body.strip()))
    text = job.body + '\n\nAn AI-generated character-inspired message.'
    unsubscribe = ''
    if unsubscribe_url:
        if urlsplit(unsubscribe_url).scheme not in {'http', 'https'}:
            raise ValueError('Unsubscribe link must use HTTP or HTTPS')
        text += '\nUnsubscribe: ' + unsubscribe_url
        unsubscribe = f'<p style="margin:12px 0 0"><a href="{escape(unsubscribe_url, quote=True)}" style="color:{ink};text-decoration:underline">Unsubscribe</a></p>'
    markup = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{subject}</title></head>
<body style="margin:0;padding:0;background-color:{bg};font-family:{font};color:{ink}">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="{bg}"><tr><td align="center" style="padding:32px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px;background-color:{card};border:1px solid {accent}">
<tr><td bgcolor="{accent}" style="padding:12px 28px;color:{accent_ink};font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;letter-spacing:3px">VOX TECH · CHARACTER LETTERS</td></tr>
<tr><td style="padding:32px 28px 24px;border-bottom:3px solid {accent}">
<p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;font-size:10px;letter-spacing:3px">A NOTE INSPIRED BY</p>
<h1 style="margin:0 0 8px;font-size:34px;line-height:1.2;overflow-wrap:anywhere">{name}</h1>
<p style="margin:0;font-size:13px;line-height:1.5">{series}</p></td></tr>
<tr><td style="padding:30px 28px 12px"><h2 style="margin:0 0 24px;font-size:23px;line-height:1.4;overflow-wrap:anywhere">{subject}</h2>{paragraphs}</td></tr>
<tr><td style="padding:20px 28px 28px;border-top:1px solid {accent};font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6">
<p style="margin:0">An AI-generated character-inspired message.</p>{unsubscribe}</td></tr>
</table></td></tr></table></body></html>'''
    return text, markup
