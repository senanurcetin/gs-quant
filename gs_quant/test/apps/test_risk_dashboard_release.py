"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / 'deploy'
CHANGELOG = ROOT / 'gs_quant' / 'apps' / 'risk_dashboard' / 'CHANGELOG.md'

pytestmark = pytest.mark.skipif(not (DEPLOY / 'pin_version.py').exists(), reason='not run from a repository checkout')


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(tmp_path) -> Path:
    """A source tree without git history, like the one a Docker build has"""
    (tmp_path / 'gs_quant').mkdir(parents=True)
    for name in ('_version.py', '__init__.py'):
        shutil.copy(ROOT / 'gs_quant' / name, tmp_path / 'gs_quant' / name)
    return tmp_path


class TestPinVersion:
    def test_writes_a_stub_that_reports_the_version(self, tmp_path):
        pin = load('pin_version')

        target = pin.pin('1.2.3', tree(tmp_path))

        spec = importlib.util.spec_from_file_location('pinned_version', target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.get_versions()['version'] == '1.2.3'

    def test_a_tree_without_git_reports_unknown_until_it_is_pinned(self, tmp_path):
        pytest.importorskip('setuptools')
        source = tree(tmp_path)
        for name in ('setup.py', 'versioneer.py', 'setup.cfg', 'pyproject.toml'):
            if (ROOT / name).exists():
                shutil.copy(ROOT / name, source / name)

        def version():
            out = subprocess.run([sys.executable, 'setup.py', '--version'], cwd=source, capture_output=True, text=True)
            return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-500:]

        assert version() == '0+unknown'
        load('pin_version').pin('4.5.6', source)
        assert version() == '4.5.6'

    def test_the_built_package_reports_the_pinned_version(self, tmp_path):
        """versioneer rewrites _version.py when it builds: what it wrote must still be the pinned version"""
        pytest.importorskip('setuptools')
        pytest.importorskip('wheel')
        pytest.importorskip('pip')
        source = tree(tmp_path / 'src')
        for name in ('setup.py', 'versioneer.py', 'setup.cfg', 'pyproject.toml'):
            if (ROOT / name).exists():
                shutil.copy(ROOT / name, source / name)
        load('pin_version').pin('4.5.6', source)

        built = subprocess.run(
            [
                sys.executable,
                '-m',
                'pip',
                'wheel',
                '.',
                '--no-deps',
                '--no-build-isolation',
                '-w',
                str(tmp_path / 'out'),
            ],
            cwd=source,
            env={**os.environ, 'PYTHONPATH': str(source)},  # setup.py imports versioneer from the tree
            capture_output=True,
            text=True,
        )

        assert built.returncode == 0, built.stderr[-800:]
        (wheel,) = (tmp_path / 'out').glob('gs_quant-*.whl')
        assert wheel.name.startswith('gs_quant-4.5.6-')
        with zipfile.ZipFile(wheel) as archive:
            inside = archive.read('gs_quant/_version.py').decode()
        namespace: dict = {}
        exec(compile(inside, '_version.py', 'exec'), namespace)  # noqa: S102 - the file this test just built
        assert namespace['get_versions']()['version'] == '4.5.6'

    @pytest.mark.parametrize('bad', ['', 'latest', '1.2', 'v1.2.3', '1.2.3; rm -rf /', "1.2.3'"])
    def test_refuses_what_is_not_a_version(self, tmp_path, bad):
        with pytest.raises(ValueError):
            load('pin_version').pin(bad, tree(tmp_path))

    def test_the_command_says_what_it_did_and_fails_cleanly(self, tmp_path, monkeypatch, capsys):
        pin = load('pin_version')
        monkeypatch.chdir(tree(tmp_path))

        assert pin.main(['2.0.0']) == 0 and 'Pinned' in capsys.readouterr().out
        assert pin.main(['nope']) == 1 and 'not a version' in capsys.readouterr().err
        assert pin.main([]) == 2
        monkeypatch.chdir(tmp_path / 'gs_quant')
        assert pin.main(['2.0.0']) == 1 and 'does not exist' in capsys.readouterr().err


SAMPLE = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-11-01

### Added
- Something.

## [0.1.0] - 2026-10-05

First release.
"""


class TestReleaseNotes:
    def test_takes_the_section_of_one_version_only(self):
        notes = load('release_notes').notes_for(SAMPLE, '0.2.0')

        assert notes == '### Added\n- Something.\n'

    def test_the_last_section_runs_to_the_end(self):
        assert load('release_notes').notes_for(SAMPLE, '0.1.0') == 'First release.\n'

    @pytest.mark.parametrize('version, message', [('9.9.9', 'no section'), ('Unreleased', 'is empty')])
    def test_a_missing_or_empty_section_stops_the_release(self, version, message):
        with pytest.raises(LookupError, match=message):
            load('release_notes').notes_for(SAMPLE, version)

    def test_the_command_prints_the_notes_or_fails(self, tmp_path, capsys):
        module = load('release_notes')
        path = tmp_path / 'CHANGELOG.md'
        path.write_text(SAMPLE, encoding='utf-8')

        assert module.main([str(path), '0.1.0']) == 0 and capsys.readouterr().out == 'First release.\n'
        assert module.main([str(path), '3.0.0']) == 1 and 'no section' in capsys.readouterr().err
        assert module.main([str(tmp_path / 'missing.md'), '0.1.0']) == 1
        assert module.main([]) == 2

    def test_the_real_changelog_has_notes_for_every_released_version(self):
        text = CHANGELOG.read_text(encoding='utf-8')
        versions = re.findall(r'^## \[(\d+\.\d+\.\d+)\]', text, re.M)

        assert versions, 'the changelog lists no release'
        for version in versions:
            assert load('release_notes').notes_for(text, version).strip()


class TestWorkflows:
    def load(self, name):
        yaml = pytest.importorskip('yaml')
        return yaml.safe_load((ROOT / '.github' / 'workflows' / name).read_text(encoding='utf-8'))

    def test_a_release_is_made_from_a_tag_after_the_checks(self):
        workflow = self.load('release.yml')
        triggers = workflow.get('on', workflow.get(True))  # YAML reads a bare `on` as True

        assert triggers == {'push': {'tags': ['release-*']}}
        assert workflow['jobs']['checks']['uses'] == './.github/workflows/ci.yml'
        publish = workflow['jobs']['publish']
        assert publish['needs'] == 'checks'
        assert publish['permissions'] == {'contents': 'write', 'packages': 'write'}
        assert workflow['permissions'] == {'contents': 'read'}

    def test_the_checks_can_be_called_by_the_release(self):
        workflow = self.load('ci.yml')
        triggers = workflow.get('on', workflow.get(True))

        assert 'workflow_call' in triggers and 'pull_request' in triggers

    def test_the_release_checks_the_image_before_pushing_it(self):
        steps = [s.get('name', '') for s in self.load('release.yml')['jobs']['publish']['steps']]

        assert steps.index('The image reports its version and asks for a token') < steps.index('Push the image')
        assert steps.index('Push the image') < steps.index('Create the GitHub release')

    def test_a_release_in_a_fork_does_not_try_to_publish_to_pypi(self):
        job = self.load('python-publish.yml')['jobs']['deploy']

        assert job['if'] == "github.repository == 'goldmansachs/gs-quant'"

    def test_the_image_takes_the_version_the_workflow_passes(self):
        dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        workflow = (ROOT / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')

        assert 'ARG VERSION' in dockerfile and 'deploy/pin_version.py' in dockerfile
        assert '--build-arg VERSION=' in workflow
        assert 'deploy' not in (ROOT / '.dockerignore').read_text(encoding='utf-8').split()

    def test_the_compose_file_for_the_published_image_does_not_build(self):
        compose = self.load('../../deploy/docker-compose.image.yml')

        assert 'build' not in compose['services']['app']
        assert compose['services']['app']['image'].startswith('ghcr.io/senanurcetin/gs-quant-risk:')
