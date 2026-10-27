"""Executable entry point. Source renderers remain editable in single/ and season/."""
from pathlib import Path
import os, sys, argparse, subprocess, json, tempfile

def main():
    root = Path(sys.executable).resolve().parents[2] if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    os.environ['TYPHOON_SKILL_ROOT'] = str(root)
    os.environ['PATH'] = str(root/'runtime/bin') + os.pathsep + os.environ.get('PATH','')
    if not getattr(sys, 'frozen', False):
        sys.path[:0] = [str(root/'runtime/python'),str(root)]
    parser = argparse.ArgumentParser(description='Typhoon animation: bundled Windows runtime, editable source retained')
    parser.add_argument('mode', choices=['single','single-config','season-plate','season-cards','season-overview','preview','preview-black','vis-clean','cloud-video','fetch-assets','pack-assets','publish-release','build-runtime','build-exe','check'])
    args = parser.parse_args(sys.argv[1:2])
    rest = sys.argv[2:]
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
    elif args.mode == 'preview':
        from scripts import track_preview
        return track_preview.main(rest)
    elif args.mode == 'preview-black':
        from single.scripts import preview_black
        return preview_black.main(rest)
    elif args.mode == 'vis-clean':
        from scripts import vis_clean
        return vis_clean.main(rest)
    elif args.mode == 'cloud-video':
        from scripts import cloud_video
        return cloud_video.main(rest)
    elif args.mode in ('fetch-assets','pack-assets','publish-release','build-runtime','build-exe'):
        # Explicit imports ensure every production tool is included by PyInstaller.
        from tools import fetch_assets, pack_assets, publish_release, build_runtime
        from scripts import build_exe
        modules = {'fetch-assets': fetch_assets, 'pack-assets': pack_assets,
                   'publish-release': publish_release, 'build-runtime': build_runtime,
                   'build-exe': build_exe}
        sys.argv = [sys.argv[0] + ' ' + args.mode] + rest
        return modules[args.mode].main()
    else:
        import numpy, PIL, cv2, yaml
        from PIL import ImageFont
        from single.scripts import typhoon_anim
        from season.scripts import season_pass1, season_pass2
        from scripts import track_preview
        for path in [typhoon_anim.F_MONO,typhoon_anim.F_CJK,season_pass2.F_BAN_EN,season_pass2.CJK_TTC]:
            ImageFont.truetype(path,24)
        assert (root/'assets/SMCY1.3/map/basins/EARTH.png').is_file()
        assert track_preview.load_pass1()._SKILL_ASSETS == str(root/'assets/SMCY1.3')
        with track_preview.Image.open(root/'assets/SMCY1.3/gui/ace_heat.png') as ramp:
            ramp.load()
        assert (root/'season/templates/ace_density_preview.html').is_file()
        assert (root/'single/templates/vis_clean_tuner.html').is_file()
        for tool in ['ffmpeg','ffprobe']:
            subprocess.run([str(root/'runtime/bin'/(tool+'.exe')),'-version'],check=True,stdout=subprocess.DEVNULL)
        # Exercise renderer cache initialization and verify actual write access.
        with tempfile.TemporaryDirectory(prefix='typhoon-check-') as project:
            for renderer in (typhoon_anim, season_pass1):
                renderer._apply_config({'paths': {
                    'storm': project, 'assets': str(root/'assets/SMCY1.3'),
                    'cache': str(root/'assets/_cache')}})
                renderer._bind_paths()
                for directory in (renderer.ICOND, renderer.FXD):
                    with tempfile.TemporaryDirectory(prefix='.write-check-', dir=directory):
                        pass
        print(json.dumps({'ok':True,'cache_writable':True,'frozen':bool(getattr(sys,'frozen',False)),'root':str(root),'numpy':numpy.__version__,'pillow':PIL.__version__,'opencv':cv2.__version__,'yaml':yaml.__version__},ensure_ascii=False))

if __name__ == '__main__':
    raise SystemExit(main())
