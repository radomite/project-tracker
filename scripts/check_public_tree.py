"""Check publishable Git files without reading ignored local data or printing secrets."""
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'data', '.checks', '.secrets', 'secrets', 'backups', 'releases',
    'node_modules', '__pycache__', 'research-diary', '.npm-cache', 'test-results', 'playwright-report'}
PATTERNS = [re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    re.compile(rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b')]


def main():
    result = subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],
        cwd=ROOT,check=True,capture_output=True)
    names = sorted(set(n.decode('utf-8') for n in result.stdout.split(b'\0') if n))
    errors = []
    total = 0
    for name in names:
        relative = PurePosixPath(name)
        path = ROOT/name
        if PRIVATE_PARTS.intersection(relative.parts) or (relative.name.startswith('.env') and relative.name != '.env.example'):
            errors.append(name+': private/runtime path is publishable')
            continue
        if path.is_symlink():
            errors.append(name+': review symlink before publishing')
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if size > 5*1024**2:
            errors.append(name+': unexpectedly large source file; generate assets during the build')
            continue
        if relative.suffix.lower() in {'.db','.sqlite','.sqlite3','.pem','.key','.pfx','.p12','.log'}:
            errors.append(name+': unexpected local data or credential file')
        raw = path.read_bytes()
        if any(pattern.search(raw) for pattern in PATTERNS):
            errors.append(name+': possible credential; review locally (value withheld)')
        if b'C:' + b'\\Users\\' in raw or b'C:' + b'/Users/' in raw:
            errors.append(name+': workstation user path')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Public-tree check passed: {len(names)} files, {total/1024**2:.2f} MiB. '
          'Ignored data was not read. Pattern checks do not replace human review.')


if __name__ == '__main__':
    main()
