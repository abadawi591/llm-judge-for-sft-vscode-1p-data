"""
Blob Reader Module
==================

Read conversation data from Azure Blob Storage.

This module handles:
    - Connecting to Azure Blob Storage
    - Listing available datasets
    - Downloading split files (train/val/test)
    - Parsing JSON conversation data
    - Flattening conversations to individual turns

Storage Structure:
    Container: github-copilot-sft-data-all-languages
    Path: experiments/testvscode_test/v4/{dataset_name}/
    
    Each dataset contains:
        ├── train/
        │   ├── short_3_to_5_turns.json
        │   ├── medium_6_to_10_turns.json
        │   └── long_11_to_20_turns.json
        ├── val/
        │   └── (same structure)
        ├── test/
        │   └── (same structure)
        └── metadata.json

Authentication:
    Uses DefaultAzureCredential (supports az login, managed identity, etc.)
"""

import json
from pathlib import Path
from typing import List, Optional, Iterator
from dataclasses import dataclass

from .schemas import TurnRecord, ConversationRecord


# Azure Blob Storage configuration
STORAGE_ACCOUNT_URL = "https://githubtelemetry.blob.core.windows.net"
CONTAINER_NAME = "github-copilot-sft-data-all-languages"
BASE_PATH = "experiments/testvscode_test/v4"

# Bucket files within each split
BUCKET_FILES = [
    "short_3_to_5_turns.json",
    "medium_6_to_10_turns.json",
    "long_11_to_20_turns.json",
]

# Data splits
SPLITS = ["train", "val", "test"]


@dataclass
class DatasetInfo:
    """Information about an available dataset."""
    name: str
    path: str
    splits: List[str]
    has_metadata: bool


class BlobDataReader:
    """
    Read conversation data from Azure Blob Storage.
    
    This class provides methods to:
    - List available datasets
    - Download split data (train/val/test)
    - Parse and flatten conversations to turns
    
    Example:
        >>> reader = BlobDataReader()
        >>> 
        >>> # List datasets
        >>> datasets = reader.list_datasets()
        >>> print(datasets[0].name)
        
        >>> # Download train split
        >>> conversations = reader.download_split("train", dataset_name="...")
        >>> 
        >>> # Flatten to turns
        >>> turns = reader.flatten_to_turns(conversations)
        >>> print(f"Total turns: {len(turns)}")
    """
    
    def __init__(self, use_keyvault: bool = True):
        """
        Initialize blob reader.
        
        Args:
            use_keyvault: Whether to use Key Vault for auth (not needed for blob)
        """
        self._container_client = None
    
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
    
    def list_datasets(self) -> List[DatasetInfo]:
        """
        List available datasets in blob storage.
        
        Returns:
            List of DatasetInfo objects
        """
        container = self._get_container_client()
        
        # List directories under base path
        datasets = []
        prefix = f"{BASE_PATH}/"
        
        # Get unique dataset directories
        seen_datasets = set()
        for blob in container.list_blobs(name_starts_with=prefix):
            # Extract dataset name from path
            parts = blob.name[len(prefix):].split("/")
            if len(parts) >= 2:
                dataset_name = parts[0]
                if dataset_name not in seen_datasets:
                    seen_datasets.add(dataset_name)
                    
                    # Check what splits exist
                    splits = []
                    for split in SPLITS:
                        split_prefix = f"{prefix}{dataset_name}/{split}/"
                        # Check if any blobs exist in this split
                        for _ in container.list_blobs(name_starts_with=split_prefix):
                            splits.append(split)
                            break
                    
                    # Check for metadata
                    metadata_path = f"{prefix}{dataset_name}/metadata.json"
                    has_metadata = any(
                        b.name == metadata_path 
                        for b in container.list_blobs(name_starts_with=metadata_path)
                    )
                    
                    datasets.append(DatasetInfo(
                        name=dataset_name,
                        path=f"{prefix}{dataset_name}",
                        splits=splits,
                        has_metadata=has_metadata,
                    ))
        
        return datasets
    
    def download_split(
        self,
        split: str,
        dataset_name: str,
        buckets: Optional[List[str]] = None,
    ) -> List[ConversationRecord]:
        """
        Download a data split from blob storage.
        
        Args:
            split: Data split (train/val/test)
            dataset_name: Name of the dataset directory
            buckets: Specific buckets to download (default: all)
        
        Returns:
            List of ConversationRecord objects
        """
        if split not in SPLITS:
            raise ValueError(f"Invalid split '{split}'. Must be one of {SPLITS}")
        
        container = self._get_container_client()
        
        # Determine which bucket files to download
        bucket_files = buckets if buckets else BUCKET_FILES
        
        conversations = []
        for bucket_file in bucket_files:
            blob_path = f"{BASE_PATH}/{dataset_name}/{split}/{bucket_file}"
            
            try:
                # Download blob content
                blob_client = container.get_blob_client(blob_path)
                content = blob_client.download_blob().readall()
                
                # Parse JSON (array of conversations)
                data = json.loads(content)
                
                # Extract bucket name from filename
                bucket = bucket_file.replace(".json", "")
                
                # Convert to ConversationRecord objects
                for conv_data in data:
                    conv = ConversationRecord.from_dict(conv_data, split=split)
                    conv.bucket = bucket
                    conversations.append(conv)
                
                print(f"  ✓ {split}/{bucket_file}: {len(data):,} conversations")
                
            except Exception as e:
                print(f"  ⚠ {split}/{bucket_file}: {e}")
        
        return conversations
    
    def download_all_splits(
        self,
        dataset_name: str,
        splits: Optional[List[str]] = None,
    ) -> dict:
        """
        Download all splits for a dataset.
        
        Args:
            dataset_name: Name of the dataset directory
            splits: Specific splits to download (default: all)
        
        Returns:
            Dict mapping split name to list of ConversationRecord
        """
        splits_to_download = splits if splits else SPLITS
        
        result = {}
        for split in splits_to_download:
            print(f"\nDownloading {split} split...")
            result[split] = self.download_split(split, dataset_name)
        
        return result
    
    def flatten_to_turns(
        self,
        conversations: List[ConversationRecord],
    ) -> List[TurnRecord]:
        """
        Flatten conversations to individual turn records.
        
        Each conversation has multiple turns. This method extracts
        each turn as a separate TurnRecord for labeling.
        
        Args:
            conversations: List of conversation records
        
        Returns:
            List of TurnRecord (one per user message)
        """
        turns = []
        for conv in conversations:
            turns.extend(conv.to_turn_records())
        return turns


# Module-level convenience functions

def list_available_datasets() -> List[DatasetInfo]:
    """List available datasets in blob storage."""
    reader = BlobDataReader()
    return reader.list_datasets()


def download_split(
    split: str,
    dataset_name: str,
    buckets: Optional[List[str]] = None,
) -> List[ConversationRecord]:
    """Download a data split from blob storage."""
    reader = BlobDataReader()
    return reader.download_split(split, dataset_name, buckets)


def flatten_conversations_to_turns(
    conversations: List[ConversationRecord],
) -> List[TurnRecord]:
    """Flatten conversations to individual turn records."""
    reader = BlobDataReader()
    return reader.flatten_to_turns(conversations)

