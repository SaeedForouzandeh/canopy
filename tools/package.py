"""Build a clean, deterministic source archive for distribution."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '2.1.0'
INCLUDE_DIRS = ['canopy', 'dashboard', 'templates', 'static', 'docs', 'tools', '.github']
INCLUDE_FILES = ['manage.py', 'requirements.txt', 'requirements-dev.txt', 'README.md', 'LICENSE', '.gitignore', '.env.example']

def main():
    destination = ROOT / 'dist' / f'canopy-wiseland-studio-v{VERSION}.zip'
    destination.parent.mkdir(exist_ok=True)
    files = [ROOT / name for name in INCLUDE_FILES]
    for directory in INCLUDE_DIRS:
        files.extend(path for path in (ROOT / directory).rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'})
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, Path(f'canopy-{VERSION}') / path.relative_to(ROOT))
    print(f'Created {destination} ({destination.stat().st_size / 1024:.0f} KB, {len(files)} files)')

if __name__ == '__main__':
    main()
