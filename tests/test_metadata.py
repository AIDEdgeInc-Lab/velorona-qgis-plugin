"""metadata.txt must survive the QGIS plugin repository's parser (configparser with interpolation): a literal '%' has to be '%%'."""
import configparser
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metadata.txt")


def test_metadata_parses_with_interpolation():
    parser = configparser.ConfigParser()
    parser.read(PATH, encoding="utf-8")
    values = {key: parser["general"][key] for key in parser["general"]}   # raises InterpolationSyntaxError on a lone '%'
    assert values["version"] and values["changelog"] and values["description"]


def test_percent_values_keep_their_wording():
    parser = configparser.ConfigParser()
    parser.read(PATH, encoding="utf-8")
    assert "5.8 % of endpoints have several" in parser["general"]["about"] + parser["general"]["changelog"]
