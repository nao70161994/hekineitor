import urllib.parse


def safe_work_url(url):
    if not url:
        return ''
    parsed = urllib.parse.urlparse(str(url).strip())
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    return urllib.parse.urlunparse(parsed)


def parse_work_item(raw) -> 'str | dict':
    """Normalize one work item from API/admin input."""
    if isinstance(raw, dict):
        title = str(raw.get('title', '')).strip()
        url = safe_work_url(raw.get('url', ''))
        if not title:
            return ''
        return {'title': title, 'url': url} if url else title
    s = str(raw).strip()
    if '|' in s:
        title, _, url = s.partition('|')
        title = title.strip()
        url = safe_work_url(url)
        if title and url:
            return {'title': title, 'url': url}
        return title
    return s


def parse_works_list(raw_list: list) -> list:
    """Normalize a list of work items and drop blank entries."""
    result = []
    for item in raw_list:
        parsed = parse_work_item(item)
        if parsed:
            result.append(parsed)
    return result


def work_title(work) -> str:
    if isinstance(work, dict):
        return str(work.get('title', '')).strip()
    return str(work).strip()
