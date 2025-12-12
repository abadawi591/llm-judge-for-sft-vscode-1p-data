"""
IO Module
=========

Input/Output handling for the soft-label teacher pipeline.

This module provides:
    - blob_reader: Read conversation data from Azure Blob Storage
    - blob_writer: Write labeled data to Azure Blob Storage
    - schemas: Data validation and output schemas

Data Storage:
    Azure Blob Storage container: github-copilot-sft-data-all-languages
    Path: experiments/testvscode_test/v4/
    
    RAW Data (read-only):
        {dataset_name}/
            ├── train/short_3_to_5_turns.json
            ├── val/medium_6_to_10_turns.json
            └── metadata.json
    
    LABELED Data (write):
        LABELED_{dataset_name}/
            ├── train/short_3_to_5_turns.jsonl
            ├── val/medium_6_to_10_turns.jsonl
            └── labeling_metadata.json

SAFETY: Raw data is NEVER modified. Labeled data goes to a parallel folder.
"""

from .blob_reader import (
    BlobDataReader,
    list_available_datasets,
    download_split,
    flatten_conversations_to_turns,
)
from .blob_writer import (
    BlobDataWriter,
    WriteStats,
    LabelingMetadata,
    get_labeled_folder_name,
    write_labeled_records,
    create_labeling_metadata,
)
from .schemas import (
    TurnRecord,
    LabeledTurnRecord,
    ConversationRecord,
)

__all__ = [
    # Reader
    "BlobDataReader",
    "list_available_datasets",
    "download_split",
    "flatten_conversations_to_turns",
    # Writer
    "BlobDataWriter",
    "WriteStats",
    "LabelingMetadata",
    "get_labeled_folder_name",
    "write_labeled_records",
    "create_labeling_metadata",
    # Schemas
    "TurnRecord",
    "LabeledTurnRecord",
    "ConversationRecord",
]

