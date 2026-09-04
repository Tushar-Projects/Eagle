"""Extraction package for ingesting transaction data into CanonicalRecords."""

from eagle.extraction._llama_vision import LlamaServerVisionProvider
from eagle.extraction._mock_vision import MockVisionProvider
from eagle.extraction._nvidia_nim import (
    NvidiaNimVisionProvider,
    build_vision_prompt_instructions,
    parse_vision_json_response,
)
from eagle.extraction.csv_extractor import CsvExtractor, ExtractionValidationError, extract_csv
from eagle.extraction.json_extractor import JsonExtractor, extract_json
from eagle.extraction.models import DocumentExtractionResult, RawExtractedTransaction
from eagle.extraction.normalizer import (
    assemble_canonical_record,
    normalize_amount,
    normalize_currency,
    normalize_date,
)
from eagle.extraction.pdf_extractor import PdfExtractor
from eagle.extraction.router import ExtractorRouter
from eagle.extraction.vision_extractor import VisionExtractor, build_vision_system_prompt

__all__ = [
    "CsvExtractor",
    "extract_csv",
    "JsonExtractor",
    "extract_json",
    "PdfExtractor",
    "VisionExtractor",
    "MockVisionProvider",
    "LlamaServerVisionProvider",
    "NvidiaNimVisionProvider",
    "build_vision_prompt_instructions",
    "build_vision_system_prompt",
    "parse_vision_json_response",
    "ExtractorRouter",
    "RawExtractedTransaction",
    "DocumentExtractionResult",
    "ExtractionValidationError",
    "assemble_canonical_record",
    "normalize_amount",
    "normalize_currency",
    "normalize_date",
]
