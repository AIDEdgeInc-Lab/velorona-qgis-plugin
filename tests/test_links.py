"""Help links: public GitHub/guide pages only, no tracking parameters. Pure stdlib."""
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import links  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_bug_and_feature_links_open_the_repositorys_issue_forms():
    bug = urlparse(links.bug_url("1.1.11"))
    assert (bug.scheme, bug.netloc, bug.path) == ("https", "github.com", "/AIDEdgeInc-Lab/velorona-qgis-plugin/issues/new")
    assert parse_qs(bug.query) == {"template": ["bug.yml"], "plugin_version": ["1.1.11"]}
    assert parse_qs(urlparse(links.feature_url()).query) == {"template": ["feature.yml"]}
    assert links.bug_url() == "https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/issues/new?template=bug.yml"


def test_the_templates_exist_and_the_prefilled_field_id_matches():
    tpl = os.path.join(ROOT, ".github", "ISSUE_TEMPLATE")
    for name in ("bug.yml", "feature.yml"):
        assert os.path.exists(os.path.join(tpl, name)), name
    assert "id: plugin_version" in open(os.path.join(tpl, "bug.yml"), encoding="utf-8").read()


def test_no_tracking_in_any_link():
    for url in (links.bug_url("x"), links.feature_url(), links.DOCS_URL):
        assert not any(k in url for k in ("utm_", "ref=", "source=", "fbclid", "gclid")), url
