"""Compatibility CLI for season stills; implementation lives in scripts.track_preview."""
from pathlib import Path
import os
import sys
root = Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[2])
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
from scripts.track_preview import render_season

def main(argv=None):
    return render_season(sys.argv[1:] if argv is None else argv)

if __name__ == '__main__':
    main()
