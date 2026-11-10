"""Release metadata stays consistent: package version, changelog, workflow."""

import re
from pathlib import Path

import tasklane

ROOT = Path(__file__).resolve().parent.parent


def _project_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"', text, flags=re.M).group(1)


def test_package_version_matches_pyproject():
    assert tasklane.__version__ == _project_version()


def test_changelog_has_an_entry_for_the_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
    assert _project_version() in headings
    assert headings[0] == _project_version()  # newest first


def test_release_workflow_uses_trusted_publishing_on_version_tags():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text
    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish" in text
    assert "password:" not in text  # no stored API token
