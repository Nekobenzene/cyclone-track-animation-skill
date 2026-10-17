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
    args = parser.parse_args(argv)
    shared = Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[2])
    sys.path.insert(0, str(shared / 'runtime/python'))
    os.environ['PATH'] = str(shared / 'runtime/bin') + os.pathsep + os.environ.get('PATH', '')
    import typhoon_anim as renderer
    if args.config:
        renderer.main(['--config', str(args.config.resolve()), 'preview-black'])
    else:
        import launch
        launch.main([str(args.project.resolve()), 'preview-black'], renderer_module=renderer)


if __name__ == '__main__':
    main()
