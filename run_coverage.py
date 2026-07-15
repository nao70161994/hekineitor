import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    os.chdir(ROOT)
    subprocess.run([sys.executable, '-m', 'coverage', 'erase'], check=True)
    result = subprocess.run(
        [sys.executable, '-m', 'coverage', 'run', '-m', 'pytest', '-q'],
        check=False,
    )
    if result.returncode:
        return result.returncode
    return subprocess.run(
        [sys.executable, '-m', 'coverage', 'report'],
        check=False,
    ).returncode


if __name__ == '__main__':
    sys.exit(main())
