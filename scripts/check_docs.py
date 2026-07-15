import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r'!?\[[^]]*\]\(([^)]+)\)')


def markdown_files():
    yield ROOT / 'README.md'
    yield ROOT / 'CLAUDE.md'
    for path in sorted((ROOT / 'docs').rglob('*.md')):
        yield path


def main() -> int:
    failures = []
    for path in markdown_files():
        text = path.read_text(encoding='utf-8')
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip().strip('<>')
            if not target or target.startswith(('#', '/', 'http://', 'https://', 'mailto:')):
                continue
            target = unquote(target.split('#', 1)[0].split('?', 1)[0])
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                failures.append(f'{path.relative_to(ROOT)}: missing link target {raw_target}')
    if failures:
        print('\n'.join(failures))
        return 1
    print('Documentation links: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
