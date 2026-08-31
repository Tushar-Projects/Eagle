"""Extraction package for ingesting transaction data into CanonicalRecords."""

from eagle.extraction.csv_extractor import CsvExtractor, ExtractionValidationError, extract_csv
from eagle.extraction.json_extractor import JsonExtractor, extract_json
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.normalizer import assemble_canonical_record, normalize_amount, normalize_currency, normalize_date
from eagle.extraction.pdf_extractor import PdfExtractor
from eagle.extraction.router import ExtractorRouter
from eagle.extraction.vision_extractor import VisionExtractor
from eagle.extraction._mock_vision import MockVisionProvider

__all__ = [
    "CsvExtractor",
    "extract_csv",
    "JsonExtractor",
    "extract_json",
    "PdfExtractor",
    "VisionExtractor",
    "MockVisionProvider",
    "ExtractorRouter",
    "RawExtractedTransaction",
    "DocumentExtractionResult",
    "ExtractionValidationError",
    "assemble_canonical_record",
    "normalize_amount",
    "normalize_currency",
    "normalize_date",
]
