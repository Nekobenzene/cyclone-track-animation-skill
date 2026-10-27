"""Rebuild the Windows executable from retained source; requires Python 3.12 and pip."""
from pathlib import Path
import os, sys, tempfile, subprocess, json, hashlib, argparse
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_support import skill_root, python_command

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', help='External Python 3.12 executable, required when rebuilding from frozen mode')
    args = parser.parse_args()
    root = skill_root()
    python = python_command(args.python)
    probe = subprocess.check_output(python + ['-c', 'import sys,struct; print(sys.platform, *sys.version_info[:2], struct.calcsize("P")*8)'], text=True).strip()
    if probe != 'win32 3 12 64':
        raise SystemExit('Build with Windows x64 Python 3.12 to match bundled native wheels')
    with tempfile.TemporaryDirectory(prefix='typhoon-build-') as temp:
        work = Path(temp); tools = work/'tools'
        subprocess.run(python+['-m','pip','install','--disable-pip-version-check','--target',str(tools),'pyinstaller==6.16.0'],check=True)
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join([str(root/'runtime/python'),str(tools)])
        command = python+['-m','PyInstaller','--noconfirm','--clean','--onedir','--console',
                   '--name','typhoon','--distpath',str(root/'bin'),'--workpath',str(work/'build'),
                   '--specpath',str(work),'--paths',str(root),'--paths',str(root/'runtime/python'),
                   '--collect-submodules','PIL','--hidden-import','yaml','--hidden-import','cv2',
                   str(root/'scripts/typhoon_app.py')]
        subprocess.run(command,check=True,env=env)
    sources = sorted(p for folder in ('single/scripts','season/scripts','scripts','tools','season/templates','single/templates') for p in (root/folder).glob('*') if p.suffix in ('.py','.html'))
    (root/'bin/typhoon/source_manifest.json').write_text(json.dumps({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2),encoding='utf-8')
    print('Built:',root/'bin/typhoon/typhoon.exe')

if __name__ == '__main__':
    main()
