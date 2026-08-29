"""Extraction package for ingesting transaction data into CanonicalRecords."""

from eagle.extraction.csv_extractor import CsvExtractor, extract_csv
from eagle.extraction.json_extractor import JsonExtractor, extract_json

__all__ = [
    "CsvExtractor",
    "extract_csv",
    "JsonExtractor",
    "extract_json",
]
