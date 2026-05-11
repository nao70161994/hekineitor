import ast
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / 'app.py',
    ROOT / 'engine.py',
    ROOT / 'analytics.py',
    ROOT / 'audit.py',
    ROOT / 'matrix_service.py',
    ROOT / 'storage.py',
    ROOT / 'work_utils.py',
    ROOT / 'tests',
]


class StaticVisitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.errors = []

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec'}:
            self.errors.append((node.lineno, f'avoid {node.func.id}()'))
        self.generic_visit(node)


def iter_python_files():
    for target in TARGETS:
        if target.is_dir():
            yield from sorted(target.rglob('*.py'))
        elif target.exists():
            yield target


def main():
    failures = []
    for path in iter_python_files():
        source = path.read_text(encoding='utf-8')
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            failures.append(f'{path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}')
            continue
        visitor = StaticVisitor(path)
        visitor.visit(tree)
        for lineno, message in visitor.errors:
            failures.append(f'{path.relative_to(ROOT)}:{lineno}: {message}')
    if failures:
        print('\n'.join(failures))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
