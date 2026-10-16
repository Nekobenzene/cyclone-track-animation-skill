"""Rebuild the Windows executable from retained source; requires Python 3.12 and pip."""
from pathlib import Path
import os, sys, tempfile, subprocess, json, hashlib

def main():
    root = Path(__file__).resolve().parents[1]
    if sys.platform != 'win32' or sys.version_info[:2] != (3,12):
        raise SystemExit('Build with Windows x64 Python 3.12 to match bundled native wheels')
    with tempfile.TemporaryDirectory(prefix='typhoon-build-') as temp:
        work = Path(temp); tools = work/'tools'
        subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--target',str(tools),'pyinstaller==6.16.0'],check=True)
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join([str(root/'runtime/python'),str(tools)])
        command = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--console',
                   '--name','typhoon','--distpath',str(root/'bin'),'--workpath',str(work/'build'),
                   '--specpath',str(work),'--paths',str(root),'--paths',str(root/'runtime/python'),
                   '--collect-submodules','PIL','--hidden-import','yaml','--hidden-import','cv2',
                   str(root/'scripts/typhoon_app.py')]
        subprocess.run(command,check=True,env=env)
    sources = [*list((root/'single/scripts').glob('*.py')),*list((root/'season/scripts').glob('*.py')),*list((root/'scripts').glob('*.py'))]
    (root/'bin/typhoon/source_manifest.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2),encoding='utf-8')
    print('Built:',root/'bin/typhoon/typhoon.exe')

if __name__ == '__main__':
    main()
