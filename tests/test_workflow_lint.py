"""Real actionlint checks when installed; dedicated lint CI always installs it."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACTIONLINT = shutil.which('actionlint')


@unittest.skipUnless(ACTIONLINT, 'Install actionlint 1.7.12 to run workflow expression checks; lint CI requires it')
class WorkflowLint(unittest.TestCase):
    def test_all_workflows_pass_actionlint(self):
        result = subprocess.run([str(ROOT / 'tools/lint_workflows.sh')], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actionlint_rejects_original_job_env_regression(self):
        text = (ROOT / '.github/workflows/publish-image.yml').read_text()
        job, steps = text.split('    steps:\n', 1)
        self.assertNotIn('runner.temp', job)
        self.assertEqual(steps.count('DOCKER_CONFIG: ${{ runner.temp }}/wan-docker-auth'), 2)
        broken = job.replace('    env:\n', '    env:\n      DOCKER_CONFIG: ${{ runner.temp }}/wan-docker-auth\n', 1) + '    steps:\n' + steps
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / 'broken.yml'
            workflow.write_text(broken)
            result = subprocess.run([ACTIONLINT, str(workflow)], cwd=ROOT,
                                    capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('context "runner" is not allowed here', result.stdout + result.stderr)
