"""Render the standard single track preview on a solid black background."""
from pathlib import Path
import argparse
import os
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--project', type=Path, help='Storm folder containing sourcedata/')
    source.add_argument('--config', type=Path, help='Existing storm YAML')
    parser.add_argument('--layers',choices=['both','track','heat'],default='track')
    parser.add_argument('--size',default='native')
    args = parser.parse_args(argv)
    shared = Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[2])
    if not getattr(sys, 'frozen', False):
        sys.path[:0] = [str(shared), str(shared / 'runtime/python')]
    os.environ['PATH'] = str(shared / 'runtime/bin') + os.pathsep + os.environ.get('PATH', '')
    from single.scripts import typhoon_anim as renderer
    if args.config:
        renderer.main(['--config', str(args.config.resolve()), 'preview-black','--layers',args.layers,'--size',args.size])
    else:
        from single.scripts import launch
        launch.main([str(args.project.resolve()), 'preview-black','--layers',args.layers,'--size',args.size], renderer_module=renderer)


if __name__ == '__main__':
    main()
