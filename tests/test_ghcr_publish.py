"""Offline publishing guards; no registry calls, Docker build, or credentials."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ghcr_publish as publish

TAG = 'git-' + 'a' * 40
REFERENCE = publish.IMAGE + '@sha256:' + 'b' * 64


class RegistryGuards(unittest.TestCase):
    def test_new_package_allowed_only_before_push(self):
        with patch.object(publish, 'api', return_value=None):
            publish.guard(TAG, True)
            with self.assertRaisesRegex(RuntimeError, 'privacy could not be verified'):
                publish.guard(TAG, False)

    def test_private_package_allowed_public_or_unknown_rejected(self):
        with patch.object(publish, 'api', side_effect=[{'visibility': 'private'}, []]):
            publish.guard(TAG, True)
        for visibility in ('public', 'internal', None):
            with self.subTest(visibility=visibility), patch.object(publish, 'api', return_value={'visibility': visibility}):
                with self.assertRaisesRegex(RuntimeError, 'must be private'):
                    publish.guard(TAG, True)
                with self.assertRaisesRegex(RuntimeError, 'must be private'):
                    publish.guard(TAG, False)

    def test_existing_commit_tag_rejected_on_later_page(self):
        duplicate = {'metadata': {'container': {'tags': [TAG]}}}
        with patch.object(publish, 'api', side_effect=[{'visibility': 'private'}, [{}] * 100, [duplicate]]) as api:
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                publish.guard(TAG, True)
            self.assertIn('page=2', api.call_args.args[0])

    def test_tag_lookup_failure_does_not_allow_overwrite(self):
        with patch.object(publish, 'api', side_effect=[{'visibility': 'private'}, None]):
            with self.assertRaisesRegex(RuntimeError, 'Cannot list package tags'):
                publish.guard(TAG, True)
        for tag in ('latest', 'git-1234567', 'invalid\nvalue'):
            with self.assertRaisesRegex(RuntimeError, 'full commit'):
                publish.guard(tag, True)

    def test_api_auth_errors_do_not_disclose_token_or_response(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'fixture-secret'}):
            for status in (401, 403, 429, 500):
                error = urllib.error.HTTPError('https://api.github.com/test', status, 'fixture-secret', {}, io.BytesIO(b'fixture-secret'))
                with patch.object(publish.urllib.request, 'urlopen', side_effect=error):
                    with self.assertRaises(RuntimeError) as context:
                        publish.api(publish.PACKAGE)
                    self.assertNotIn('fixture-secret', str(context.exception))
                    self.assertIn(str(status), str(context.exception))
            missing = urllib.error.HTTPError('https://api.github.com/test', 404, 'missing', {}, None)
            with patch.object(publish.urllib.request, 'urlopen', side_effect=missing):
                self.assertIsNone(publish.api(publish.PACKAGE))

    def test_api_uses_token_header_and_no_missing_token_request(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(publish.urllib.request, 'urlopen') as opener:
            with self.assertRaisesRegex(RuntimeError, 'GITHUB_TOKEN'):
                publish.api(publish.PACKAGE)
            opener.assert_not_called()
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(b'{"visibility":"private"}'))
        response.__exit__ = Mock(return_value=False)
        with patch.dict(os.environ, {'GH_TOKEN': 'fixture-secret'}), patch.object(publish.urllib.request, 'urlopen', return_value=response) as opener:
            self.assertEqual(publish.api(publish.PACKAGE)['visibility'], 'private')
            self.assertEqual(opener.call_args.args[0].get_header('Authorization'), 'Bearer fixture-secret')

    def test_low_disk_stops_without_deleting_anything(self):
        with patch.object(publish.shutil, 'disk_usage', return_value=Mock(free=1024**3)):
            with self.assertRaisesRegex(RuntimeError, 'larger CPU runner'):
                publish.disk_check()
        with patch.object(publish.shutil, 'disk_usage', return_value=Mock(free=20*1024**3)):
            publish.disk_check()

    def test_digest_is_registry_reference_never_local_image_id(self):
        self.assertEqual(publish.registry_digest([REFERENCE]), REFERENCE)
        for entries in ([], ['sha256:' + 'b' * 64], ['another/image@sha256:' + 'b' * 64], [REFERENCE, publish.IMAGE + '@sha256:' + 'c' * 64]):
            with self.assertRaisesRegex(RuntimeError, 'registry RepoDigest'):
                publish.registry_digest(entries)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'digests.json').write_text(json.dumps([REFERENCE]))
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(path / 'outputs'), 'GITHUB_STEP_SUMMARY': str(path / 'summary'), 'GITHUB_SHA': 'a'*40}):
                publish.report(path / 'digests.json')
            self.assertIn('image=' + REFERENCE, (path / 'outputs').read_text())
            self.assertIn(REFERENCE, (path / 'summary').read_text())


class WorkflowContract(unittest.TestCase):
    def test_original_no_publish_workflow_is_unchanged(self):
        data = (ROOT / '.github/workflows/image.yml').read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        self.assertEqual(blob, '12a6e692d565c46a5f5db8c178d495e1dd354054')

    def test_manual_only_minimum_permissions_and_no_archive(self):
        workflow = (ROOT / '.github/workflows/publish-image.yml').read_text()
        events = workflow.split('on:\n', 1)[1].split('\npermissions:', 1)[0]
        self.assertIn('workflow_dispatch:', events)
        self.assertNotRegex(events, r'(?m)^  (push|pull_request|schedule|workflow_run):')
        self.assertIn('packages: write', workflow)
        self.assertIn('contents: read', workflow)
        self.assertNotIn('id-token:', workflow)
        self.assertIn('secrets.GITHUB_TOKEN', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        for forbidden in ('docker save', 'upload-artifact', ':latest', 'build-arg', 'docker system prune', 'rm -rf'):
            self.assertNotIn(forbidden, workflow)
        self.assertIn('--platform linux/amd64', workflow)
        self.assertIn('ghcr.io/imissthefuhrer/wan-cloud-toolkit', workflow)
        self.assertIn('--password-stdin', workflow)
        self.assertIn('docker logout ghcr.io', workflow)

    def test_checks_precede_single_push_and_scripts_parse(self):
        workflow = (ROOT / '.github/workflows/publish-image.yml').read_text()
        stages = ['python3 -m unittest', 'docker build --platform', 'python3.11 tools/check_image.py', 'docker push', 'ghcr_publish.py private', 'ghcr_publish.py report']
        indexes = [workflow.index(stage) for stage in stages]
        self.assertEqual(indexes, sorted(indexes))
        self.assertEqual(workflow.count('docker push'), 1)
        self.assertEqual(workflow.count('ghcr_publish.py preflight'), 2)
        blocks = re.findall(r'        run: \|\n((?:          .*\n|\n)+)', workflow)
        self.assertGreaterEqual(len(blocks), 4)
        for block in blocks:
            script = '\n'.join(line[10:] for line in block.splitlines())
            result = subprocess.run(['bash', '-n'], input=script, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
