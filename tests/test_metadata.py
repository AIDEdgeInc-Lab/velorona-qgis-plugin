"""metadata.txt must survive the QGIS plugin repository's parser (configparser with interpolation): a literal '%' has to be '%%'."""
import configparser
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metadata.txt")


def test_metadata_parses_with_interpolation():
    parser = configparser.ConfigParser()
    parser.read(PATH, encoding="utf-8")
    values = {key: parser["general"][key] for key in parser["general"]}   # raises InterpolationSyntaxError on a lone '%'
    assert values["version"] and values["changelog"] and values["description"]


def test_every_literal_percent_sign_is_escaped_in_the_raw_file():
    """The guard the old wording test stood for: the repository's parser rejects a lone '%', so every '%' in metadata.txt must be part of '%%'."""
    raw = open(PATH, encoding="utf-8").read()
    assert "%" not in raw.replace("%%", ""), "a lone '%' in metadata.txt would be rejected by the plugin repository"


def test_the_changelog_field_is_the_current_release_only():
    """The listing's changelog is the concise notes for the version being published; the full history lives in CHANGELOG.md."""
    parser = configparser.ConfigParser()
    parser.read(PATH, encoding="utf-8")
    changelog = parser["general"]["changelog"]
    version = parser["general"]["version"]
    assert changelog.startswith(f"{version} - ")
    assert len(changelog) < 8000, len(changelog)
