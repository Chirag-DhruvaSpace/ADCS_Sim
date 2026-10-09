# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
"""Vite build delivery without starting a physics simulation."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import app


class FrontendServingTests(unittest.TestCase):
    def test_build_and_fingerprinted_assets_have_distinct_cache_policies(self):
        with TemporaryDirectory() as directory:
            dist = Path(directory) / 'frontend' / 'dist'
            (dist / 'assets').mkdir(parents=True)
            (dist / 'index.html').write_text('<div id="root"></div>', encoding='utf-8')
            (dist / 'assets' / 'viewer-abc123.js').write_text('export const ready=true;', encoding='utf-8')
            with patch.object(app.app, 'root_path', directory):
                client = app.app.test_client()
                with client.get('/') as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers['Cache-Control'], 'no-cache')
                    self.assertIn(b'id="root"', response.data)
                with client.get('/frontend/assets/viewer-abc123.js') as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('immutable', response.headers['Cache-Control'])
                    self.assertIn('javascript', response.mimetype)
                self.assertEqual(client.get('/frontend/../../app.py').status_code, 404)

    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    def test_missing_build_reports_setup_instead_of_loading_old_ui(self):
        with TemporaryDirectory() as directory, patch.object(app.app, 'root_path', directory):
            with app.app.test_client().get('/') as response:
                self.assertEqual(response.status_code, 503)
                self.assertIn(b'npm run build', response.data)

    def test_shared_assets_support_video_ranges_and_reject_traversal(self):
        with TemporaryDirectory() as directory:
            media = Path(directory) / 'frontend' / 'assets' / 'media'
            media.mkdir(parents=True)
            (media / 'reference.mp4').write_bytes(bytes(range(128)))
            with patch.object(app.app, 'root_path', directory):
                client = app.app.test_client()
                with client.get('/assets/media/reference.mp4', headers={'Range': 'bytes=10-19'}) as response:
                    self.assertEqual(response.status_code, 206)
                    self.assertEqual(response.data, bytes(range(10, 20)))
                self.assertEqual(client.get('/assets/../../app.py').status_code, 404)
                self.assertEqual(client.get('/ground/track/no/yaw/steering').location, '/')

    def test_viewer_bootstrap_includes_model_lighting_and_pointing(self):
        data = app.app.test_client().get('/api/viewer/config').json
        self.assertIn('spacecraft_model_url', data)
        self.assertEqual(len(data['spacecraft_com']), 3)
        self.assertIn('earth_day_ambient', data['viewer_lighting'])
        self.assertIn(data['pointing_strategy'], ('legacy', 'custom', 'firmware_sitl'))


if __name__ == '__main__':
    unittest.main()
