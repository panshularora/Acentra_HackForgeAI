"""Mask protected health information (PHI) in log text.

Everything the service stores, shows or sends to AWS passes through
:func:`mask` first, which follows the HIPAA "minimum necessary" idea: the
on-call engineer needs to know *that* member lookups are failing, not *whose*.

:func:`message_template` goes one step further for grouping: after masking it
replaces free-standing numbers, so "timeout after 5012ms" and "timeout after
4980ms" count as the same error.
"""

import re

# US phone numbers. Area codes never start with 0 or 1. Groups separated only
# by spaces are also left alone inside a longer run of numbers, so
# "sizes 128 256 512 1024" survives while "555 123 4567" is masked.
_PHONE = re.compile(
    r"""
    (?:\+1[-.\ ]?|\b1[-.])?                     # optional country code
    (?:\([2-9]\d{2}\)\s?|\b[2-9]\d{2}[-.])      # (555) 123-4567, 555-123-4567, 555.123.4567
    \d{3}[-.\ ]\d{4}\b
    |
    (?<![\d.]\ )(?:\+1[-.\ ]?)?                 # not preceded by another number
    \b[2-9]\d{2}\ \d{3}\ \d{4}\b(?!\ \d)        # 555 123 4567, not followed by one
    """,
    re.VERBOSE,
)

# Order matters: SSNs (3-2-4 digits) must be replaced before the phone pattern
# gets a chance to match part of them, and quoted names before bare ones.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\bname="[^"]*"'), 'name="<NAME>"'),
    (re.compile(r"\bname=(?!\")\S+"), "name=<NAME>"),
    (re.compile(r"\b(dob|date_of_birth)=\S+"), r"\1=<DOB>"),
    (re.compile(r"\bmember_id=(?!<)\S+"), "member_id=<MEMBER_ID>"),
    (re.compile(r"\bM\d{7}\b"), "<MEMBER_ID>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<EMAIL>"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
    (_PHONE, "<PHONE>"),
    # Unformatted numbers are only treated as phones with a +1 prefix or a
    # phone key; a bare run of ten digits is as likely to be a claim number.
    (re.compile(r"\+1[2-9]\d{9}\b"), "<PHONE>"),
    (re.compile(r"\b(phone|mobile)=\d{10}\b"), r"\1=<PHONE>"),
)

# A number that is not part of a word, a placeholder or a dotted IP address.
_NUMBER = re.compile(r"(?<![\w.<])\d+(?:\.\d+)?(?![\d.]*\d)")


def mask(text: str) -> str:
    """Replace member IDs, names, dates of birth, emails, SSNs and phone numbers with tags."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def message_template(message: str) -> str:
    """Mask PHI and replace stray numbers with ``<N>`` so similar errors group together."""
    return _NUMBER.sub("<N>", mask(message))
