import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEGACY_ENGINE_SHIMS = {path.stem for path in ROOT.glob('engine_*.py')}


def _legacy_shim_import_allowed(path):
    relative = path.resolve().relative_to(ROOT)
    return bool(relative.parts and relative.parts[0] in {'tests', 'scripts'})


class StaticVisitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.errors = []

    def _check_legacy_engine_import(self, module_name, lineno):
        root_module = str(module_name or '').split('.', 1)[0]
        if root_module in LEGACY_ENGINE_SHIMS and not _legacy_shim_import_allowed(self.path):
            self.errors.append((lineno, f'import {root_module} via engine.*; top-level module is a compatibility shim'))

    def visit_Import(self, node):
        for alias in node.names:
            self._check_legacy_engine_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        self._check_legacy_engine_import(node.module, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec'}:
            self.errors.append((node.lineno, f'avoid {node.func.id}()'))
        self.generic_visit(node)


def iter_python_files():
    result = subprocess.run(
        ['git', 'ls-files', '-z', '--', '*.py'],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    for relative_path in result.stdout.decode().split('\0'):
        if relative_path:
            yield ROOT / relative_path


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
