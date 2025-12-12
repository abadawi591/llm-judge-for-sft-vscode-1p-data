"""
Blob Writer Module
==================

Write labeled turn data to Azure Blob Storage.

SAFETY PRINCIPLES:
    1. NEVER modify or delete files in the RAW data folder
    2. ONLY write to a NEW folder with LABELED_ prefix
    3. Create parallel folder structure (same splits/buckets)
    4. Write JSONL format (one line per turn)

Storage Structure:
    Container: github-copilot-sft-data-all-languages
    
    RAW (read-only):
        experiments/testvscode_test/v4/{dataset_name}/
            ├── train/short_3_to_5_turns.json
            ├── val/medium_6_to_10_turns.json
            └── ...
    
    LABELED (write):
        experiments/testvscode_test/v4/LABELED_{dataset_name}/
            ├── train/short_3_to_5_turns.jsonl
            ├── val/medium_6_to_10_turns.jsonl
            └── labeling_metadata.json

Why This Approach:
    - No risk of data corruption (never touch RAW)
    - No copy/move operations (just create new files)
    - Clear naming convention (LABELED_ prefix)
    - Easy to join (parallel paths)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from .schemas import LabeledTurnRecord


# Azure Blob Storage configuration
STORAGE_ACCOUNT_URL = "https://githubtelemetry.blob.core.windows.net"
CONTAINER_NAME = "github-copilot-sft-data-all-languages"
BASE_PATH = "experiments/testvscode_test/v4"

# Output folder prefix
LABELED_PREFIX = "LABELED_"


@dataclass
class WriteStats:
    """Statistics from a write operation."""
    split: str
    bucket: str
    records_written: int
    blob_path: str
    bytes_written: int = 0


@dataclass 
class LabelingMetadata:
    """Metadata about the labeling job."""
    source_dataset: str
    labeled_dataset: str
    labeling_started: str
    labeling_completed: str
    model: str
    strategy: str
    with_rationales: bool
    total_turns_labeled: int
    errors: int
    splits: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_dataset": self.source_dataset,
            "labeled_dataset": self.labeled_dataset,
            "labeling_started": self.labeling_started,
            "labeling_completed": self.labeling_completed,
            "model": self.model,
            "strategy": self.strategy,
            "with_rationales": self.with_rationales,
            "total_turns_labeled": self.total_turns_labeled,
            "errors": self.errors,
            "splits": self.splits,
        }


class BlobDataWriter:
    """
    Write labeled turn data to Azure Blob Storage.
    
    This class writes labeled data to a LABELED_ prefixed folder,
    preserving the original stratification structure.
    
    SAFETY: This class NEVER modifies or deletes existing data.
    It only creates new files in the LABELED_ folder.
    
    Example:
        >>> writer = BlobDataWriter(source_dataset="vscodedata_120k_...")
        >>> 
        >>> # Write a batch of labeled records
        >>> stats = writer.write_batch(
        ...     labeled_records,
        ...     split="train",
        ...     bucket="short_3_to_5_turns"
        ... )
        >>> print(f"Wrote {stats.records_written} records to {stats.blob_path}")
        >>> 
        >>> # Finalize with metadata
        >>> writer.write_metadata(metadata)
    """
    
    def __init__(
        self,
        source_dataset: str,
        output_prefix: str = LABELED_PREFIX,
    ):
        """
        Initialize blob writer.
        
        Args:
            source_dataset: Name of the source (RAW) dataset folder
            output_prefix: Prefix for output folder (default: LABELED_)
        """
        self.source_dataset = source_dataset
        self.output_dataset = f"{output_prefix}{source_dataset}"
        self._container_client = None
        
    @property
    def output_path(self) -> str:
        """Full blob path to output folder."""
        return f"{BASE_PATH}/{self.output_dataset}"
    
    def _get_container_client(self):
        """Lazy initialization of blob container client."""
        if self._container_client is None:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import ContainerClient
            except ImportError:
                raise ImportError(
                    "Azure Blob dependencies not installed. "
                    "Install with: pip install azure-identity azure-storage-blob"
                )
            
            credential = DefaultAzureCredential()
            self._container_client = ContainerClient(
                account_url=STORAGE_ACCOUNT_URL,
                container_name=CONTAINER_NAME,
                credential=credential,
            )
        
        return self._container_client
    
    def get_blob_path(self, split: str, bucket: str) -> str:
        """
        Get the blob path for a split/bucket combination.
        
        Args:
            split: Data split (train/val/test)
            bucket: Stratification bucket (short_3_to_5_turns, etc.)
        
        Returns:
            Blob path like: experiments/.../LABELED_.../train/short_3_to_5_turns.jsonl
        """
        # Ensure .jsonl extension for per-turn output
        return f"{self.output_path}/{split}/{bucket}.jsonl"
    
    def write_batch(
        self,
        records: List[LabeledTurnRecord],
        split: str,
        bucket: str,
        append: bool = True,
    ) -> WriteStats:
        """
        Write a batch of labeled records to blob storage.
        
        Args:
            records: List of labeled turn records
            split: Data split (train/val/test)
            bucket: Stratification bucket
            append: If True, append to existing blob (default: True)
        
        Returns:
            WriteStats with details about what was written
        
        Note:
            Records are written as JSONL (one JSON object per line).
        """
        if not records:
            return WriteStats(
                split=split,
                bucket=bucket,
                records_written=0,
                blob_path=self.get_blob_path(split, bucket),
            )
        
        container = self._get_container_client()
        blob_path = self.get_blob_path(split, bucket)
        blob_client = container.get_blob_client(blob_path)
        
        # Convert records to JSONL
        lines = []
        for record in records:
            line = json.dumps(record.to_dict(), ensure_ascii=False)
            lines.append(line)
        
        content = "\n".join(lines) + "\n"
        content_bytes = content.encode("utf-8")
        
        # Upload (append mode not directly supported, need to read+append)
        if append:
            try:
                # Try to read existing content
                existing = blob_client.download_blob().readall()
                content_bytes = existing + content_bytes
            except Exception:
                # Blob doesn't exist yet, that's fine
                pass
        
        # Upload content
        blob_client.upload_blob(content_bytes, overwrite=True)
        
        return WriteStats(
            split=split,
            bucket=bucket,
            records_written=len(records),
            blob_path=blob_path,
            bytes_written=len(content_bytes),
        )
    
    def write_records_by_bucket(
        self,
        records: List[LabeledTurnRecord],
    ) -> Dict[str, Dict[str, WriteStats]]:
        """
        Write records organized by their split and bucket.
        
        This method groups records by their split/bucket fields
        and writes them to the appropriate files.
        
        Args:
            records: List of labeled turn records (with split/bucket set)
        
        Returns:
            Nested dict: {split: {bucket: WriteStats}}
        """
        # Group records by split and bucket
        grouped: Dict[str, Dict[str, List[LabeledTurnRecord]]] = {}
        
        for record in records:
            split = record.split or "unknown"
            bucket = record.bucket or "unknown"
            
            if split not in grouped:
                grouped[split] = {}
            if bucket not in grouped[split]:
                grouped[split][bucket] = []
            
            grouped[split][bucket].append(record)
        
        # Write each group
        results: Dict[str, Dict[str, WriteStats]] = {}
        
        for split, buckets in grouped.items():
            results[split] = {}
            for bucket, bucket_records in buckets.items():
                stats = self.write_batch(bucket_records, split, bucket)
                results[split][bucket] = stats
                print(f"  ✓ {split}/{bucket}: {stats.records_written:,} turns")
        
        return results
    
    def write_metadata(self, metadata: LabelingMetadata) -> str:
        """
        Write labeling metadata to blob storage.
        
        Args:
            metadata: LabelingMetadata object
        
        Returns:
            Blob path where metadata was written
        """
        container = self._get_container_client()
        blob_path = f"{self.output_path}/labeling_metadata.json"
        blob_client = container.get_blob_client(blob_path)
        
        content = json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False)
        blob_client.upload_blob(content.encode("utf-8"), overwrite=True)
        
        return blob_path
    
    def check_output_exists(self) -> bool:
        """
        Check if the output folder already exists.
        
        Returns:
            True if any blobs exist in the output folder
        """
        container = self._get_container_client()
        prefix = f"{self.output_path}/"
        
        # Check if any blobs exist with this prefix
        for _ in container.list_blobs(name_starts_with=prefix):
            return True
        
        return False
    
    def list_existing_output(self) -> List[str]:
        """
        List existing files in the output folder.
        
        Returns:
            List of blob paths in the output folder
        """
        container = self._get_container_client()
        prefix = f"{self.output_path}/"
        
        return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]


# Module-level convenience functions

def get_labeled_folder_name(source_dataset: str) -> str:
    """Get the LABELED_ prefixed folder name for a source dataset."""
    return f"{LABELED_PREFIX}{source_dataset}"


def write_labeled_records(
    records: List[LabeledTurnRecord],
    source_dataset: str,
) -> Dict[str, Dict[str, WriteStats]]:
    """
    Write labeled records to blob storage, organized by split/bucket.
    
    Args:
        records: List of labeled turn records
        source_dataset: Name of the source (RAW) dataset
    
    Returns:
        Nested dict of WriteStats by split and bucket
    """
    writer = BlobDataWriter(source_dataset)
    return writer.write_records_by_bucket(records)


def create_labeling_metadata(
    source_dataset: str,
    model: str,
    strategy: str,
    with_rationales: bool,
    total_turns: int,
    errors: int,
    splits_stats: Dict[str, Dict[str, int]],
    started: datetime,
) -> LabelingMetadata:
    """
    Create a metadata object for the labeling job.
    
    Args:
        source_dataset: Name of the source dataset
        model: Model used for labeling
        strategy: Labeling strategy name
        with_rationales: Whether rationales were generated
        total_turns: Total turns labeled
        errors: Number of errors
        splits_stats: Nested dict of counts by split/bucket
        started: When labeling started
    
    Returns:
        LabelingMetadata object
    """
    return LabelingMetadata(
        source_dataset=source_dataset,
        labeled_dataset=get_labeled_folder_name(source_dataset),
        labeling_started=started.isoformat(),
        labeling_completed=datetime.utcnow().isoformat(),
        model=model,
        strategy=strategy,
        with_rationales=with_rationales,
        total_turns_labeled=total_turns,
        errors=errors,
        splits=splits_stats,
    )

