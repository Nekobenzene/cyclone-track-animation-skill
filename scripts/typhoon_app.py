"""Executable entry point. Source renderers remain editable in single/ and season/."""
from pathlib import Path
import os, sys, argparse, subprocess, json

def main():
    root = Path(sys.executable).resolve().parents[2] if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    os.environ['TYPHOON_SKILL_ROOT'] = str(root)
    os.environ['PATH'] = str(root/'runtime/bin') + os.pathsep + os.environ.get('PATH','')
    if not getattr(sys, 'frozen', False):
        sys.path[:0] = [str(root/'runtime/python'),str(root)]
    parser = argparse.ArgumentParser(description='Typhoon animation: bundled Windows runtime, editable source retained')
    parser.add_argument('mode', choices=['single','single-config','season-plate','season-cards','season-overview','check'])
    args, rest = parser.parse_known_args()
    if args.mode == 'single':
        from single.scripts import launch, typhoon_anim
        launch.main(rest, renderer_module=typhoon_anim)
    elif args.mode == 'single-config':
        from single.scripts import typhoon_anim
        typhoon_anim.main(rest)
    elif args.mode == 'season-plate':
        from season.scripts import season_pass1
        season_pass1.main(rest)
    elif args.mode == 'season-cards':
        from season.scripts import season_pass2
        season_pass2.main(rest)
    elif args.mode == 'season-overview':
        from season.scripts import season_overview
        season_overview.main(rest)
    else:
        import numpy, PIL, cv2, yaml
        from PIL import ImageFont
        from single.scripts import typhoon_anim
        from season.scripts import season_pass1, season_pass2, season_overview
        for path in [typhoon_anim.F_MONO,typhoon_anim.F_CJK,season_pass2.F_BAN_EN,season_pass2.CJK_TTC]:
            ImageFont.truetype(path,24)
        assert (root/'assets/SMCY1.3/map/basins/EARTH.png').is_file()
        assert season_overview.load_pass1()._SKILL_ASSETS == str(root/'assets/SMCY1.3')
        for tool in ['ffmpeg','ffprobe']:
            subprocess.run([str(root/'runtime/bin'/(tool+'.exe')),'-version'],check=True,stdout=subprocess.DEVNULL)
        print(json.dumps({'ok':True,'frozen':bool(getattr(sys,'frozen',False)),'root':str(root),'numpy':numpy.__version__,'pillow':PIL.__version__,'opencv':cv2.__version__,'yaml':yaml.__version__},ensure_ascii=False))

if __name__ == '__main__':
    main()
