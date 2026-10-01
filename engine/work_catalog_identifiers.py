"""Canonical identifiers for works and their editions."""

import hashlib
import re

_ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})', re.IGNORECASE)
_IDENTIFIER_SCHEME_RE = re.compile(r'^[a-z][a-z0-9._-]{0,31}$')
_IDENTIFIER_AUTHORITY_RE = re.compile(r'^[a-z0-9][a-z0-9._:-]{0,99}$')
_ISBN_CLEAN_RE = re.compile(r'[^0-9Xx]')


def stable_id(prefix, *parts):
    payload = '\x1f'.join(str(part or '') for part in parts)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]
    return f'{prefix}_{digest}'


def extract_asin(url):
    match = _ASIN_RE.search(str(url or ''))
    return match.group(1).upper() if match else ''


def normalize_isbn(value):
    """Validate ISBN-10/13 and return the canonical ISBN-13 digits."""
    cleaned = _ISBN_CLEAN_RE.sub('', str(value or ''))
    if len(cleaned) == 10:
        if not cleaned[:9].isdigit() or (not cleaned[-1].isdigit() and cleaned[-1].upper() != 'X'):
            raise ValueError('invalid ISBN-10')
        digits = [int(char) for char in cleaned[:9]]
        check = 10 if cleaned[-1].upper() == 'X' else int(cleaned[-1])
        if (sum((10 - index) * digit for index, digit in enumerate(digits)) + check) % 11:
            raise ValueError('invalid ISBN-10 checksum')
        prefix = f'978{cleaned[:9]}'
        total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(prefix))
        return f'{prefix}{(10 - total % 10) % 10}'
    if len(cleaned) == 13 and cleaned.isdigit():
        total = sum((1 if index % 2 == 0 else 3) * int(char) for index, char in enumerate(cleaned[:12]))
        if (10 - total % 10) % 10 != int(cleaned[-1]):
            raise ValueError('invalid ISBN-13 checksum')
        return cleaned
    raise ValueError('ISBN must contain 10 or 13 digits')


def normalize_edition_identifier(*, scheme, authority, value):
    """Return one canonical non-ASIN edition identifier tuple."""
    normalized_scheme = str(scheme or '').strip().lower()
    normalized_authority = str(authority or '').strip().lower()
    normalized_value = str(value or '').strip()
    if not _IDENTIFIER_SCHEME_RE.fullmatch(normalized_scheme):
        raise ValueError('invalid edition identifier scheme')
    if normalized_scheme == 'asin':
        raise ValueError('ASIN must remain in work_editions.asin')
    if normalized_scheme == 'isbn':
        normalized_authority = 'isbn'
        normalized_value = normalize_isbn(normalized_value)
    else:
        if not _IDENTIFIER_AUTHORITY_RE.fullmatch(normalized_authority):
            raise ValueError('invalid edition identifier authority')
        if not normalized_value or len(normalized_value) > 200 or any(ord(char) < 32 for char in normalized_value):
            raise ValueError('invalid edition identifier value')
    return normalized_scheme, normalized_authority, normalized_value


def build_edition_identifier(edition_id, *, scheme, authority='', value):
    """Build a deterministic canonical identifier row."""
    edition_id = str(edition_id or '').strip()
    if not edition_id:
        raise ValueError('edition_id is required')
    scheme, authority, value = normalize_edition_identifier(
        scheme=scheme,
        authority=authority,
        value=value,
    )
    return {
        'identifier_id': stable_id('wei', scheme, authority, value),
        'edition_id': edition_id,
        'scheme': scheme,
        'authority': authority,
        'value': value,
    }
