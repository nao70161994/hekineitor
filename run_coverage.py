import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
result = subprocess.run(
    [sys.executable, '-m', 'coverage', 'run', '--source=app,engine',
     '-m', 'unittest', 'tests.test_app'],
    capture_output=False
)
if result.returncode == 0:
    subprocess.run([sys.executable, '-m', 'coverage', 'report', '-m'])
else:
    sys.exit(result.returncode)
