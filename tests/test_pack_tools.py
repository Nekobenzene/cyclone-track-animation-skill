"""Release URLs keep unchanged packs downloadable across partial releases."""
from unittest import TestCase
from tools.fetch_assets import pack_url

class PackUrlTests(TestCase):
    def test_pack_url_is_pinned_but_mirror_override_wins(self):
        manifest = {'repo':'owner/repo','tag':'assets-v2',
                    'url_template':'https://github.com/{repo}/releases/download/{tag}/{file}',
                    'packs':{'map':{'file':'map.zip','url':'https://example.org/assets-v1/map.zip'}}}
        self.assertEqual(pack_url(manifest,'map',None),'https://example.org/assets-v1/map.zip')
        self.assertEqual(pack_url(manifest,'map','https://mirror.invalid/packs'),'https://mirror.invalid/packs/map.zip')
        del manifest['packs']['map']['url']
        self.assertEqual(pack_url(manifest,'map',None),'https://github.com/owner/repo/releases/download/assets-v2/map.zip')
