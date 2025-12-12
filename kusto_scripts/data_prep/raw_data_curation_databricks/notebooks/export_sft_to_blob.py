"""
SFT Data Export to Azure Blob Storage

This script exports curated SFT conversation data from Kusto/ADX to Azure Blob Storage.
Supports train/val/test splits with mutual exclusivity guaranteed by hash-based partitioning.

Features:
- TIME CHUNKING: Splits large queries into smaller time chunks to avoid OOM/timeouts
- Retry logic with exponential backoff for transient failures
- Sequential split execution to minimize OOM risk
- Progress tracking and resumable exports

Usage:
    1. Ensure you're logged in: az login
    2. Run: python export_sft_to_blob.py [--test] [--split SPLIT]

    --test:        Run with test query (~10 records) instead of production (~120k)
    --split SPLIT: Export only one split (train/val/test). If not specified, exports all.

Recommended Production Usage (safest):
    python export_sft_to_blob.py --split train
    python export_sft_to_blob.py --split val
    python export_sft_to_blob.py --split test

Output Structure:
    github-copilot-sft-data-all-languages/experiments/testvscode_test/v4/
    └── vscodedata_120k_complete_stratified_deduped_60d_YYYYMMDD/
        ├── train/     (100k: 40k + 40k + 20k)
        │   ├── short_3_to_5_turns.json
        │   ├── medium_6_to_10_turns.json
        │   └── long_11_to_20_turns.json
        ├── val/       (10k: 4k + 4k + 2k)
        │   ├── short_3_to_5_turns.json
        │   ├── medium_6_to_10_turns.json
        │   └── long_11_to_20_turns.json
        ├── test/      (10k: 4k + 4k + 2k)
        │   ├── short_3_to_5_turns.json
        │   ├── medium_6_to_10_turns.json
        │   └── long_11_to_20_turns.json
        └── metadata.json

Split Sizes:
    - Train: 100,000 conversations (40k short + 40k medium + 20k long)
    - Val:    10,000 conversations (4k short + 4k medium + 2k long)
    - Test:   10,000 conversations (4k short + 4k medium + 2k long)
    - TOTAL: 120,000 conversations

Mutual Exclusivity:
    Uses hash(conversationId) % 100 for deterministic partitioning:
    - hash % 100 < 83  → Train (83%)
    - hash % 100 < 92  → Val   (9%)
    - hash % 100 >= 92 → Test  (8%)
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
import hashlib

# Progress bar
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("Note: Install tqdm for progress bars: pip install tqdm")

# Tenacity for robust retry logic
try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        wait_random_exponential,
        retry_if_exception_type,
        before_sleep_log,
        after_log,
    )
    import logging
    TENACITY_AVAILABLE = True
    
    # Setup logging for tenacity
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
except ImportError:
    TENACITY_AVAILABLE = False
    print("Note: Install tenacity for robust retries: pip install tenacity")

# Azure SDK imports
from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.helpers import dataframe_from_result_table
from azure.kusto.data.exceptions import KustoApiError, KustoServiceError
from azure.storage.blob import BlobServiceClient
from requests.exceptions import RequestException, ConnectionError, Timeout
from concurrent.futures import TimeoutError as FuturesTimeoutError

# =============================================================================
# RETRY CONFIGURATION (used by tenacity)
# =============================================================================
MAX_RETRIES = 5  # Increased from 3 to 5
RETRY_MIN_WAIT = 30  # Minimum wait between retries (seconds)
RETRY_MAX_WAIT = 300  # Maximum wait between retries (5 minutes)
RETRY_MULTIPLIER = 2  # Exponential backoff multiplier

# =============================================================================
# CHUNKING CONFIGURATION  
# =============================================================================
ENABLE_CHUNKING = True
CHUNKING_METHOD = "hash"  # "hash" (recommended) or "time"

# Hash-based chunking (RECOMMENDED): Guarantees conversation completeness
# 60 chunks to balance data size and query count
NUM_HASH_CHUNKS = 60  # Number of hash buckets (60 chunks = ~1.67% data per chunk)
HASH_CHUNK_DELAY_SECONDS = 3  # Delay between chunks

# Time-based chunking (legacy): May split conversations across chunks
CHUNK_DAYS = 2  # Query 2 days at a time (60 days = 30 chunks)
TIME_CHUNK_DELAY_SECONDS = 3  # Delay between chunks

# =============================================================================
# TIMEOUT CONFIGURATION
# =============================================================================
SERVER_TIMEOUT_SECONDS = 900   # ~15 minutes - Kusto server-side timeout
CLIENT_TIMEOUT_SECONDS = 900   # ~15 minutes - Client-side timeout (most chunks complete in 1-3 min)

# =============================================================================
# CONFIGURATION
# =============================================================================

KUSTO_CLUSTER = "https://ade.loganalytics.io/subscriptions/d0c05057-7972-46ff-9bcf-3c932250155e/resourceGroups/CopilotChatEval/providers/Microsoft.OperationalInsights/workspaces/d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2"
KUSTO_DATABASE = "d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2"

STORAGE_ACCOUNT_URL = "https://githubtelemetry.blob.core.windows.net"
STORAGE_CONTAINER = "github-copilot-sft-data-all-languages"
BLOB_BASE_PATH = "experiments/testvscode_test/v4"

# Query files relative to this script
SCRIPT_DIR = Path(__file__).parent.parent
TEST_QUERY_FILE = SCRIPT_DIR / "queries" / "sft_test_100_with_trajectory.kql"  # Full trajectory version
PROD_QUERY_FILE = SCRIPT_DIR / "queries" / "sft_100k_production_with_splits.kql"
# No-sampling query for time-based chunked aggregation (legacy)
CANDIDATES_QUERY_FILE = SCRIPT_DIR / "queries" / "sft_candidates_no_sampling.kql"
# Hash-based chunking query (RECOMMENDED) - guarantees conversation completeness
HASH_CHUNKED_QUERY_FILE = SCRIPT_DIR / "queries" / "sft_candidates_hash_chunked.kql"

# Checkpoint file for resumable exports
CHECKPOINT_FILE = SCRIPT_DIR / "notebooks" / "checkpoint.json"

# Split configuration
# Train: 100k, Val: 10k, Test: 10k → Total 120k
SPLITS = ["train", "val", "test"]
SPLIT_RATIOS = {"train": 0.833, "val": 0.083, "test": 0.083}  # ~83% / ~9% / ~8%

# Sample sizes by split and bucket
SAMPLE_SIZES = {
    "production": {
        "train": {"short": 40000, "medium": 40000, "long": 20000},  # 100k total
        "val": {"short": 4000, "medium": 4000, "long": 2000},       # 10k total
        "test": {"short": 4000, "medium": 4000, "long": 2000},      # 10k total
    },
    "test": {
        "train": {"short": 40, "medium": 40, "long": 20},  # 100 total
        "val": {"short": 4, "medium": 4, "long": 2},       # 10 total
        "test": {"short": 4, "medium": 4, "long": 2},      # 10 total
    }
}


# =============================================================================
# SPLIT ASSIGNMENT
# =============================================================================

def get_split(conversation_id: str) -> str:
    """
    Deterministically assign a conversation to train/val/test based on hash.
    This matches the Kusto query logic: hash(conversationId) % 100
    
    Split ratios (Train: 100k, Val: 10k, Test: 10k → Total 120k):
    - hash < 83  → Train (83%)
    - hash < 92  → Val (9%)
    - hash >= 92 → Test (8%)
    """
    # Use SHA256 hash to match Kusto's hash() function behavior
    hash_value = int(hashlib.sha256(conversation_id.encode()).hexdigest(), 16) % 100
    
    if hash_value < 83:
        return "train"
    elif hash_value < 92:
        return "val"
    else:
        return "test"


# =============================================================================
# CHECKPOINT FUNCTIONS (for resumable exports)
# =============================================================================

def save_checkpoint(results: list, last_completed_chunk: int, seen_ids: set):
    """Save intermediate results to checkpoint file."""
    checkpoint_data = {
        "last_completed_chunk": last_completed_chunk,
        "total_records": len(results),
        "seen_conversation_ids": list(seen_ids),
        "results": results,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    # Write to temp file first, then rename (atomic operation)
    temp_file = CHECKPOINT_FILE.with_suffix('.tmp')
    with open(temp_file, 'w') as f:
        json.dump(checkpoint_data, f)
    temp_file.rename(CHECKPOINT_FILE)
    
    print(f"   💾 Checkpoint saved: {len(results):,} records, chunk {last_completed_chunk + 1}")


def load_checkpoint() -> tuple:
    """
    Load checkpoint if exists.
    
    Returns:
        (results, last_completed_chunk, seen_ids) or ([], -1, set()) if no checkpoint
    """
    if not CHECKPOINT_FILE.exists():
        return [], -1, set()
    
    try:
        with open(CHECKPOINT_FILE, 'r') as f:
            data = json.load(f)
        
        results = data.get("results", [])
        last_chunk = data.get("last_completed_chunk", -1)
        seen_ids = set(data.get("seen_conversation_ids", []))
        timestamp = data.get("timestamp", "unknown")
        
        print(f"\n{'='*70}")
        print(f"📂 CHECKPOINT FOUND!")
        print(f"{'='*70}")
        print(f"   Last completed chunk: {last_chunk + 1}")
        print(f"   Records saved: {len(results):,}")
        print(f"   Saved at: {timestamp}")
        print(f"   Resuming from chunk {last_chunk + 2}...")
        print(f"{'='*70}\n")
        
        return results, last_chunk, seen_ids
        
    except Exception as e:
        print(f"⚠️  Failed to load checkpoint: {e}")
        print(f"   Starting from scratch...")
        return [], -1, set()


def clear_checkpoint():
    """Remove checkpoint file after successful completion."""
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print(f"   🗑️  Checkpoint cleared")


# =============================================================================
# KUSTO CLIENT
# =============================================================================

def get_kusto_client():
    """Create authenticated Kusto client using Azure CLI credentials."""
    credential = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        KUSTO_CLUSTER, credential
    )
    return KustoClient(kcsb)


class NonRetryableError(Exception):
    """Errors that should not be retried (e.g., OOM, semantic errors)."""
    pass


def _is_retryable_error(exception: Exception) -> bool:
    """Determine if an exception is retryable."""
    error_str = str(exception).lower()
    
    # Non-retryable errors
    non_retryable_patterns = [
        "e_low_memory",
        "low memory",
        "semanticerror",
        "syntaxerror", 
        "badargumenterror",
    ]
    
    for pattern in non_retryable_patterns:
        if pattern in error_str:
            return False
    
    # Retryable errors (network issues, timeouts, transient failures)
    retryable_patterns = [
        "network",
        "timeout",
        "client-side timeout",  # Our custom ClientTimeoutError
        "connection",
        "failed to process",
        "service unavailable",
        "too many requests",
        "rate limit",
        "503",
        "502",
        "504",
    ]
    
    for pattern in retryable_patterns:
        if pattern in error_str:
            return True
    
    # Default: retry unknown errors
    return True


def _elapsed_time_display(start_time: float, stop_event, interval: int = 10):
    """Background thread to display elapsed time during query execution."""
    import threading
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        minutes, seconds = divmod(int(elapsed), 60)
        if minutes > 0:
            print(f"\r⏱️  Query running... {minutes}m {seconds}s elapsed", end="", flush=True)
        else:
            print(f"\r⏱️  Query running... {seconds}s elapsed", end="", flush=True)
        stop_event.wait(interval)  # Update every 10 seconds


class ClientTimeoutError(Exception):
    """Raised when client-side timeout is exceeded."""
    pass


def _execute_kusto_query_inner(client, query: str, properties, show_elapsed: bool = True) -> list:
    """Inner function that executes the query - separated for tenacity decorator."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    
    start_time = time.time()
    stop_event = threading.Event()
    elapsed_thread = None
    
    # Start elapsed time display in background thread
    if show_elapsed:
        elapsed_thread = threading.Thread(
            target=_elapsed_time_display, 
            args=(start_time, stop_event, 10),  # Update every 10 seconds
            daemon=True
        )
        elapsed_thread.start()
    
    def execute_query():
        """Wrapper for query execution to run in thread pool."""
        return client.execute(KUSTO_DATABASE, query, properties=properties)
    
    try:
        # Use ThreadPoolExecutor for client-side timeout
        # IMPORTANT: Don't use context manager - it waits for threads on exit!
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(execute_query)
        try:
            response = future.result(timeout=CLIENT_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            # Shutdown without waiting - don't block on stuck query!
            executor.shutdown(wait=False, cancel_futures=True)
            raise ClientTimeoutError(
                f"Client-side timeout after {CLIENT_TIMEOUT_SECONDS}s. "
                f"The server may still be processing. Consider reducing query scope."
            )
        finally:
            # Normal cleanup - shutdown without waiting
            executor.shutdown(wait=False)
    finally:
        # Stop the elapsed time display
        stop_event.set()
        if elapsed_thread:
            elapsed_thread.join(timeout=1)
        print("\r" + " " * 50 + "\r", end="")  # Clear the elapsed time line
    
    elapsed = time.time() - start_time
    
    results = []
    for row in response.primary_results[0]:
        row_dict = {}
        for i, col in enumerate(response.primary_results[0].columns):
            value = row[i]
            if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            row_dict[col.column_name] = value
        results.append(row_dict)
    
    # Format elapsed time nicely
    minutes, seconds = divmod(int(elapsed), 60)
    if minutes > 0:
        elapsed_str = f"{minutes}m {seconds}s"
    else:
        elapsed_str = f"{elapsed:.1f}s"
    
    # Warn if query returned 0 results and ran close to timeout (possible timeout)
    if len(results) == 0 and elapsed >= (SERVER_TIMEOUT_SECONDS * 0.95):
        print(f"⚠️  Query returned 0 records in {elapsed_str} (near timeout limit of {SERVER_TIMEOUT_SECONDS}s)")
        print(f"   This may indicate a server-side timeout. Consider:")
        print(f"   1. Reducing time window (e.g., 30d instead of 60d)")
        print(f"   2. Increasing NUM_HASH_CHUNKS to reduce per-chunk data")
        print(f"   3. Increasing SERVER_TIMEOUT_SECONDS")
    else:
        print(f"✅ Query returned {len(results):,} records in {elapsed_str}")
    
    return results


def run_kusto_query(client, query: str, max_retries: int = MAX_RETRIES) -> list:
    """
    Execute Kusto query with robust retry logic using tenacity.
    
    Features:
    - Exponential backoff with jitter (30s to 5min waits)
    - Up to 5 retry attempts
    - Smart retry: only retries network/transient errors
    - Does NOT retry OOM or syntax errors
    """
    from azure.kusto.data import ClientRequestProperties
    
    # Set server-side timeout
    properties = ClientRequestProperties()
    properties.set_option(
        ClientRequestProperties.results_defer_partial_query_failures_option_name,
        False
    )
    properties.set_option("servertimeout", timedelta(seconds=SERVER_TIMEOUT_SECONDS))
    
    if TENACITY_AVAILABLE:
        # Use tenacity for robust retries
        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_random_exponential(multiplier=RETRY_MULTIPLIER, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
            retry=retry_if_exception_type((RequestException, ConnectionError, Timeout, KustoServiceError, ClientTimeoutError)),
            before_sleep=lambda retry_state: print(
                f"\n⚠️  Query failed (attempt {retry_state.attempt_number}/{max_retries})\n"
                f"   Error: {str(retry_state.outcome.exception())[:200]}...\n"
                f"   Retrying in {retry_state.next_action.sleep:.0f}s with jitter..."
            ),
            reraise=True
        )
        def _execute_with_tenacity():
            print(f"Executing Kusto query ({len(query)} chars)...")
            try:
                return _execute_kusto_query_inner(client, query, properties)
            except Exception as e:
                if not _is_retryable_error(e):
                    error_str = str(e)
                    if "e_low_memory" in error_str.lower():
                        print(f"\n❌ OUT OF MEMORY ERROR - Cannot retry")
                        print(f"   The query exceeded Kusto's memory budget.")
                        print(f"   Try: 1) Reduce time window, 2) Run one split at a time")
                    else:
                        print(f"\n❌ NON-RETRYABLE ERROR: {error_str[:200]}")
                    raise NonRetryableError(str(e)) from e
                raise
        
        try:
            return _execute_with_tenacity()
        except NonRetryableError:
            raise
        except Exception as e:
            print(f"\n❌ Query failed after {max_retries} attempts")
            print(f"   Final error: {str(e)[:300]}")
            raise
    
    else:
        # Fallback: manual retry logic if tenacity not available
        last_error = None
        
        for attempt in range(max_retries):
            try:
                print(f"Executing Kusto query ({len(query)} chars)...")
                if attempt > 0:
                    print(f"  Attempt {attempt + 1}/{max_retries}")
                
                return _execute_kusto_query_inner(client, query, properties)
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                
                # Don't retry non-retryable errors
                if not _is_retryable_error(e):
                    if "e_low_memory" in error_str.lower():
                        print(f"\n❌ OUT OF MEMORY ERROR - Cannot retry")
                    raise
                
                # Don't retry on final attempt
                if attempt == max_retries - 1:
                    print(f"\n❌ Query failed after {max_retries} attempts")
                    raise
                
                # Exponential backoff with jitter for transient errors
                import random
                base_wait = RETRY_MIN_WAIT * (RETRY_MULTIPLIER ** attempt)
                jitter = random.uniform(0, base_wait * 0.3)  # 30% jitter
                wait_time = min(base_wait + jitter, RETRY_MAX_WAIT)
                print(f"\n⚠️  Query failed (attempt {attempt + 1}/{max_retries})")
                print(f"   Error: {error_str[:200]}...")
                print(f"   Retrying in {wait_time:.0f}s...")
                time.sleep(wait_time)
        
        # Should never reach here, but just in case
        raise last_error


def modify_query_for_split(query: str, split: str) -> str:
    """Modify the production query to export a specific split."""
    # Find and uncomment the appropriate section
    if split == "train":
        # Train section should be uncommented by default
        return query
    elif split == "val":
        # Comment out train, uncomment val
        query = query.replace(
            "union trainShort, trainMedium, trainLong",
            "// union trainShort, trainMedium, trainLong"
        )
        query = query.replace(
            "// union valShort, valMedium, valLong",
            "union valShort, valMedium, valLong"
        )
        # Uncomment the rest of val section
        lines = query.split('\n')
        in_val_section = False
        new_lines = []
        for line in lines:
            if "union valShort, valMedium, valLong" in line and not line.strip().startswith("//"):
                in_val_section = True
            if in_val_section and line.strip().startswith("// |"):
                line = line.replace("// |", "|")
            if "| order by bucket asc" in line and in_val_section:
                in_val_section = False
            new_lines.append(line)
        query = '\n'.join(new_lines)
    elif split == "test":
        # Comment out train, uncomment test
        query = query.replace(
            "union trainShort, trainMedium, trainLong",
            "// union trainShort, trainMedium, trainLong"
        )
        query = query.replace(
            "// union testShort, testMedium, testLong",
            "union testShort, testMedium, testLong"
        )
        # Uncomment the rest of test section
        lines = query.split('\n')
        in_test_section = False
        new_lines = []
        for line in lines:
            if "union testShort, testMedium, testLong" in line and not line.strip().startswith("//"):
                in_test_section = True
            if in_test_section and line.strip().startswith("// |"):
                line = line.replace("// |", "|")
            if "| order by bucket asc" in line and in_test_section:
                in_test_section = False
            new_lines.append(line)
        query = '\n'.join(new_lines)
    
    return query


def modify_query_time_window(query: str, start_days_ago: int, end_days_ago: int) -> str:
    """
    Modify query to use a specific time window instead of the default.
    
    Args:
        query: The base query with 'let timeStart = ago(60d);'
        start_days_ago: Start of window (e.g., 60 for ago(60d))
        end_days_ago: End of window (e.g., 55 for ago(55d))
    
    Returns:
        Modified query with new time window
    """
    # Replace the timeStart and timeEnd declarations
    query = query.replace(
        "let timeStart = ago(60d);",
        f"let timeStart = ago({start_days_ago}d);"
    )
    query = query.replace(
        "let timeEnd = now();",
        f"let timeEnd = ago({end_days_ago}d);"
    )
    return query


def run_chunked_query(client, base_query: str, total_days: int = 60, chunk_days: int = CHUNK_DAYS) -> list:
    """
    Execute query in time chunks to avoid timeouts and OOM errors.
    
    Args:
        client: Kusto client
        base_query: The base KQL query with 'let timeStart = ago(60d);'
        total_days: Total days to query (default 60)
        chunk_days: Days per chunk (default from CHUNK_DAYS)
    
    Returns:
        Combined results from all chunks
    """
    all_results = []
    num_chunks = (total_days + chunk_days - 1) // chunk_days  # Ceiling division
    
    print(f"\n🔀 CHUNKING ENABLED: Splitting {total_days} days into {num_chunks} chunks of {chunk_days} days each")
    
    # Create progress bar if available
    chunk_range = range(num_chunks)
    if TQDM_AVAILABLE:
        chunk_range = tqdm(chunk_range, desc="Processing chunks", unit="chunk")
    
    for i in chunk_range:
        # Calculate time window for this chunk
        # Chunk 0: ago(60d) to ago(55d)
        # Chunk 1: ago(55d) to ago(50d)
        # etc.
        start_days = total_days - (i * chunk_days)
        end_days = max(0, total_days - ((i + 1) * chunk_days))
        
        chunk_num = i + 1
        if not TQDM_AVAILABLE:
            print(f"\n📦 Chunk {chunk_num}/{num_chunks}: ago({start_days}d) to ago({end_days}d)")
        
        # Modify query for this time window
        chunk_query = modify_query_time_window(base_query, start_days, end_days)
        
        try:
            chunk_results = run_kusto_query(client, chunk_query)
            
            if chunk_results:
                all_results.extend(chunk_results)
                if not TQDM_AVAILABLE:
                    print(f"   ✅ Chunk {chunk_num}: {len(chunk_results):,} records (total: {len(all_results):,})")
            else:
                if not TQDM_AVAILABLE:
                    print(f"   ℹ️  Chunk {chunk_num}: No data")
            
            # Small delay between chunks to avoid rate limiting
            if i < num_chunks - 1:
                time.sleep(CHUNK_DELAY_SECONDS)
                
        except Exception as e:
            print(f"\n❌ Chunk {chunk_num} failed: {e}")
            print(f"   You can resume from chunk {chunk_num} by adjusting time windows")
            raise
    
    print(f"\n✅ All {num_chunks} chunks processed. Total records: {len(all_results):,}")
    return all_results


def run_hash_chunked_query(client, num_chunks: int = NUM_HASH_CHUNKS) -> list:
    """
    Execute query using hash-based chunking to guarantee conversation completeness.
    
    ADVANTAGES over time-based chunking:
    - Each conversation is fully contained in exactly ONE chunk
    - No risk of splitting conversations across chunks
    - Completeness is guaranteed by the chunking method itself
    
    Args:
        client: Kusto client
        num_chunks: Number of hash buckets (default 20)
    
    Returns:
        Combined results from all chunks (complete conversations only)
    """
    # Suppress verbose Azure logging
    import logging
    logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)
    logging.getLogger('azure.identity').setLevel(logging.WARNING)
    
    # Read the hash-chunked query template
    print(f"\nReading hash-chunked query from: {HASH_CHUNKED_QUERY_FILE}")
    with open(HASH_CHUNKED_QUERY_FILE, 'r') as f:
        base_query = f.read()
    
    # Try to load checkpoint for resume
    all_results, last_completed_chunk, seen_conversation_ids = load_checkpoint()
    start_chunk = last_completed_chunk + 1
    
    chunk_times = []  # Track timing for ETA
    
    print(f"\n{'='*70}")
    print(f"🔀 HASH-BASED CHUNKING: hash(conversationId) % {num_chunks}")
    print(f"{'='*70}")
    print(f"   ✅ Guarantees: Each conversation fully in ONE chunk")
    print(f"   ✅ Guarantees: Conversation completeness preserved")
    print(f"   📊 Target: ~120k conversations across all chunks")
    if start_chunk > 0:
        print(f"   🔄 RESUMING from chunk {start_chunk + 1} (skipping {start_chunk} completed chunks)")
        print(f"   📂 Loaded {len(all_results):,} records from checkpoint")
    print(f"{'='*70}\n")
    
    overall_start = time.time()
    
    for chunk_num in range(start_chunk, num_chunks):
        chunk_start = time.time()
        
        # Progress header
        pct_complete = (chunk_num / num_chunks) * 100
        print(f"\n{'─'*70}")
        print(f"📦 CHUNK {chunk_num + 1}/{num_chunks} ({pct_complete:.0f}% complete)")
        print(f"{'─'*70}")
        
        # ETA calculation
        if chunk_times:
            avg_chunk_time = sum(chunk_times) / len(chunk_times)
            remaining_chunks = num_chunks - chunk_num
            eta_seconds = avg_chunk_time * remaining_chunks
            eta_minutes = int(eta_seconds // 60)
            eta_secs = int(eta_seconds % 60)
            print(f"   ⏱️  Avg chunk time: {avg_chunk_time:.0f}s | ETA: {eta_minutes}m {eta_secs}s")
        
        print(f"   🔍 Query: hash(conversationId) % {num_chunks} == {chunk_num}")
        
        # Replace placeholders in query
        chunk_query = base_query.replace("{NUM_CHUNKS}", str(num_chunks))
        chunk_query = chunk_query.replace("{CHUNK_NUM}", str(chunk_num))
        
        try:
            chunk_results = run_kusto_query(client, chunk_query)
            chunk_elapsed = time.time() - chunk_start
            chunk_times.append(chunk_elapsed)
            
            # =====================================================================
            # TOKEN VALIDATION (early detection of query bugs)
            # =====================================================================
            # Validate token data BEFORE processing - this catches query bugs early
            # where token fields are not being extracted correctly (e.g., wrong
            # field names, wrong case in filters, etc.)
            if chunk_results:
                try:
                    token_validation = validate_chunk_tokens(chunk_results, chunk_num)
                    
                    if token_validation["invalid"] > 0:
                        print(f"\n   ⚠️  TOKEN VALIDATION WARNING:")
                        print(f"      • Valid records: {token_validation['valid']:,}")
                        print(f"      • Invalid records: {token_validation['invalid']:,} ({token_validation['invalid_percentage']:.1f}%)")
                        if token_validation["sample_errors"]:
                            print(f"      • Sample errors:")
                            for err in token_validation["sample_errors"][:2]:
                                print(f"        - {err}")
                        
                        if token_validation["is_critical"]:
                            print(f"\n   🚨 CRITICAL: >10% of records have token issues!")
                            print(f"      This may indicate a data quality problem.")
                    else:
                        print(f"   ✅ Token validation passed ({token_validation['valid']:,} records)")
                        
                except TokenValidationError as e:
                    # ALL records have token issues - this is a query bug, fail fast!
                    print(f"\n{'='*70}")
                    print(f"🚨 CRITICAL TOKEN VALIDATION FAILURE")
                    print(f"{'='*70}")
                    print(str(e))
                    print(f"{'='*70}")
                    raise
            
            new_records = 0
            if chunk_results:
                # Deduplicate by conversationId (shouldn't happen with hash chunking, but safety)
                for record in chunk_results:
                    conv_id = record.get("conversationId", "")
                    if conv_id and conv_id not in seen_conversation_ids:
                        seen_conversation_ids.add(conv_id)
                        # Assign split based on conversationId hash
                        record["split"] = get_split(conv_id)
                        all_results.append(record)
                        new_records += 1
            
            # Chunk summary
            print(f"\n   📊 CHUNK {chunk_num + 1} SUMMARY:")
            print(f"      • Records this chunk: {len(chunk_results) if chunk_results else 0:,}")
            print(f"      • New unique records: {new_records:,}")
            print(f"      • Total accumulated:  {len(all_results):,}")
            print(f"      • Chunk time: {chunk_elapsed:.1f}s")
            
            # Bucket distribution so far (every 5 chunks)
            if (chunk_num + 1) % 5 == 0 or chunk_num == num_chunks - 1:
                bucket_counts = {"short": 0, "medium": 0, "long": 0}
                split_counts = {"train": 0, "val": 0, "test": 0}
                for r in all_results:
                    bucket = r.get("bucket", "")
                    split = r.get("split", "")
                    if "short" in bucket:
                        bucket_counts["short"] += 1
                    elif "medium" in bucket:
                        bucket_counts["medium"] += 1
                    elif "long" in bucket:
                        bucket_counts["long"] += 1
                    if split in split_counts:
                        split_counts[split] += 1
                
                print(f"\n   📈 RUNNING TOTALS (after {chunk_num + 1} chunks):")
                print(f"      Buckets: short={bucket_counts['short']:,} | medium={bucket_counts['medium']:,} | long={bucket_counts['long']:,}")
                print(f"      Splits:  train={split_counts['train']:,} | val={split_counts['val']:,} | test={split_counts['test']:,}")
            
            # SAVE CHECKPOINT after each successful chunk
            save_checkpoint(all_results, chunk_num, seen_conversation_ids)
            
            # Small delay between chunks to avoid rate limiting
            if chunk_num < num_chunks - 1:
                time.sleep(HASH_CHUNK_DELAY_SECONDS)
                
        except Exception as e:
            # Save checkpoint before failing so we can resume
            if all_results:
                save_checkpoint(all_results, chunk_num - 1, seen_conversation_ids)
            
            print(f"\n{'='*70}")
            print(f"❌ CHUNK {chunk_num + 1} FAILED")
            print(f"{'='*70}")
            print(f"   Error: {str(e)[:200]}")
            print(f"   Progress: {len(all_results):,} records from {chunk_num} chunks")
            print(f"   💾 Checkpoint saved! Restart to resume from chunk {chunk_num + 1}")
            print(f"{'='*70}")
            raise
    
    # Final summary
    total_elapsed = time.time() - overall_start
    total_minutes = int(total_elapsed // 60)
    total_secs = int(total_elapsed % 60)
    
    # Clear checkpoint on successful completion
    clear_checkpoint()
    
    print(f"\n{'='*70}")
    print(f"✅ ALL {num_chunks} CHUNKS COMPLETE!")
    print(f"{'='*70}")
    print(f"   Total conversations: {len(all_results):,}")
    print(f"   Total time: {total_minutes}m {total_secs}s")
    print(f"   Avg per chunk: {total_elapsed/(num_chunks - start_chunk):.1f}s")
    
    # Print bucket distribution
    bucket_counts = {"short_3_to_5_turns": 0, "medium_6_to_10_turns": 0, "long_11_to_20_turns": 0}
    split_counts = {"train": 0, "val": 0, "test": 0}
    for record in all_results:
        bucket = record.get("bucket", "unknown")
        split = record.get("split", "unknown")
        if bucket in bucket_counts:
            bucket_counts[bucket] += 1
        if split in split_counts:
            split_counts[split] += 1
    
    print(f"\n📊 Distribution by bucket:")
    for bucket, count in bucket_counts.items():
        print(f"   {bucket}: {count:,}")
    
    print(f"\n📊 Distribution by split (pre-sampling):")
    for split, count in split_counts.items():
        print(f"   {split}: {count:,}")
    
    return all_results


def _normalize_bucket_name(bucket: str) -> str:
    """Normalize bucket name to short/medium/long."""
    bucket_lower = bucket.lower()
    if "short" in bucket_lower:
        return "short"
    elif "medium" in bucket_lower:
        return "medium"
    elif "long" in bucket_lower:
        return "long"
    return bucket  # Return as-is if no match


def stratified_sample_in_python(all_candidates: list, sample_sizes: dict) -> dict:
    """
    Perform stratified sampling in Python after aggregating all candidates.
    
    Args:
        all_candidates: List of all candidate conversation records
        sample_sizes: Dict like {"train": {"short": 40000, "medium": 40000, "long": 20000}, ...}
    
    Returns:
        Dict with structure: {"train": {"short": [...], "medium": [...], "long": [...]}, ...}
    """
    import random
    
    # Group candidates by split and bucket
    grouped = {
        "train": {"short": [], "medium": [], "long": []},
        "val": {"short": [], "medium": [], "long": []},
        "test": {"short": [], "medium": [], "long": []},
    }
    
    for record in all_candidates:
        split = record.get("split", "train")
        # Normalize bucket name (e.g., "short_3_to_5_turns" -> "short")
        bucket_raw = record.get("bucket", "short")
        bucket = _normalize_bucket_name(bucket_raw)
        
        if split in grouped and bucket in grouped[split]:
            grouped[split][bucket].append(record)
    
    # Print counts before sampling
    print("\n📊 Candidate counts BEFORE sampling:")
    for split in ["train", "val", "test"]:
        counts = {b: len(grouped[split][b]) for b in ["short", "medium", "long"]}
        print(f"  {split}: {counts}")
    
    # Sample from each group
    sampled = {
        "train": {"short": [], "medium": [], "long": []},
        "val": {"short": [], "medium": [], "long": []},
        "test": {"short": [], "medium": [], "long": []},
    }
    
    print("\n🎲 Stratified sampling...")
    for split in ["train", "val", "test"]:
        for bucket in ["short", "medium", "long"]:
            candidates = grouped[split][bucket]
            target = sample_sizes.get(split, {}).get(bucket, 0)
            
            if len(candidates) >= target:
                sampled[split][bucket] = random.sample(candidates, target)
            else:
                # Take all if not enough
                sampled[split][bucket] = candidates
                if target > 0:
                    print(f"  ⚠️ {split}/{bucket}: Only {len(candidates)} available (wanted {target})")
            
            print(f"  {split}/{bucket}: {len(sampled[split][bucket]):,} sampled from {len(candidates):,}")
    
    return sampled


# =============================================================================
# BLOB STORAGE
# =============================================================================

def get_blob_service_client():
    """Create authenticated Blob service client using Azure CLI credentials."""
    credential = DefaultAzureCredential()
    return BlobServiceClient(STORAGE_ACCOUNT_URL, credential=credential)


def upload_json_to_blob(blob_service_client, container_name: str, blob_path: str, data):
    """Upload JSON data to Azure Blob Storage."""
    container_client = blob_service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_path)
    
    json_data = json.dumps(data, indent=2, default=str)
    blob_client.upload_blob(json_data, overwrite=True)
    print(f"  Uploaded: {blob_path} ({len(json_data):,} bytes)")


# =============================================================================
# DATA VALIDATION
# =============================================================================

class TokenValidationError(Exception):
    """Raised when token validation fails critically (indicates query bug)."""
    pass


def validate_record_tokens(record: dict) -> tuple[bool, list[str]]:
    """
    Validate token data in a record (called during fetch for early detection).
    
    This validation is critical for detecting query bugs where token data
    is not being extracted correctly.
    
    Returns:
        (is_valid, list_of_errors)
    
    Checks:
        1. totalPromptTokens_actual > 0 (at conversation level)
        2. totalCompletionTokens_actual > 0 (at conversation level)  
        3. Each turn has non-empty llmCalls list
        4. Each llmCall has actual_API.promptTokens > 0
    """
    errors = []
    conversation_id = record.get("conversationId", "unknown")[:20]
    
    # Check conversation-level token totals (new query structure uses _actual suffix)
    total_prompt = record.get("totalPromptTokens_actual", record.get("totalPromptTokens", 0))
    total_completion = record.get("totalCompletionTokens_actual", record.get("totalCompletionTokens", 0))
    
    if total_prompt == 0:
        errors.append(f"totalPromptTokens=0")
    if total_completion == 0:
        errors.append(f"totalCompletionTokens=0")
    
    # Check turns for llmCalls
    turns = record.get("turnsArray", [])
    if isinstance(turns, list):
        turns_with_empty_llm_calls = 0
        turns_with_zero_tokens = 0
        
        for i, turn in enumerate(turns):
            turn_idx = turn.get("turnIndex", i + 1)
            llm_calls = turn.get("llmCalls", [])
            
            # Check llmCalls is non-empty
            if not llm_calls or len(llm_calls) == 0:
                turns_with_empty_llm_calls += 1
            else:
                # Check each llmCall has tokens (new structure: actual_API.promptTokens)
                for j, call in enumerate(llm_calls):
                    # Support both old structure (promptTokens) and new structure (actual_API.promptTokens)
                    actual_api = call.get("actual_API", {})
                    if isinstance(actual_api, dict):
                        prompt_tokens = actual_api.get("promptTokens_(system+user+assistant+toolResults)", 
                                                       actual_api.get("promptTokens", 0))
                    else:
                        # Fallback to old structure
                        prompt_tokens = call.get("promptTokens", 0)
                    
                    if prompt_tokens == 0:
                        turns_with_zero_tokens += 1
                        break  # Only count once per turn
        
        if turns_with_empty_llm_calls > 0:
            errors.append(f"{turns_with_empty_llm_calls}/{len(turns)} turns have empty llmCalls")
        
        if turns_with_zero_tokens > 0:
            errors.append(f"{turns_with_zero_tokens}/{len(turns)} turns have zero promptTokens in llmCalls")
    
    return len(errors) == 0, errors


def validate_chunk_tokens(records: list, chunk_num: int, threshold: float = 0.1) -> dict:
    """
    Validate token data for an entire chunk of records.
    
    Args:
        records: List of conversation records
        chunk_num: Chunk number (for reporting)
        threshold: Fraction of invalid records that triggers a critical error (default 10%)
    
    Returns:
        Dict with validation results:
        {
            "total": int,
            "valid": int,
            "invalid": int,
            "invalid_percentage": float,
            "is_critical": bool,  # True if invalid% > threshold
            "sample_errors": list  # Sample of error messages
        }
    
    Raises:
        TokenValidationError: If ALL records have token issues (indicates query bug)
    """
    total = len(records)
    if total == 0:
        return {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "invalid_percentage": 0.0,
            "is_critical": False,
            "sample_errors": []
        }
    
    valid = 0
    invalid = 0
    sample_errors = []
    
    for record in records:
        is_valid, errors = validate_record_tokens(record)
        if is_valid:
            valid += 1
        else:
            invalid += 1
            if len(sample_errors) < 3:  # Keep first 3 error samples
                conv_id = record.get("conversationId", "unknown")[:20]
                sample_errors.append(f"{conv_id}...: {errors}")
    
    invalid_pct = (invalid / total) * 100 if total > 0 else 0
    is_critical = (invalid / total) > threshold if total > 0 else False
    
    # If ALL records have token issues, this is a query bug - fail fast!
    if invalid == total and total > 0:
        raise TokenValidationError(
            f"CRITICAL: ALL {total} records in chunk {chunk_num + 1} have token validation errors!\n"
            f"This indicates a query bug - token data is not being extracted correctly.\n"
            f"Sample errors: {sample_errors[:3]}\n\n"
            f"Check that the query uses:\n"
            f"  - message_direction == 'output' (lowercase)\n"
            f"  - Properties['headerRequestId'] for messageId\n"
            f"  - Properties['baseModel'] for model"
        )
    
    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "invalid_percentage": invalid_pct,
        "is_critical": is_critical,
        "sample_errors": sample_errors
    }


def validate_record(record: dict, expected_split: str = None) -> tuple[bool, list[str]]:
    """
    Validate a single conversation record.
    Returns (is_valid, list_of_errors).
    
    Args:
        record: The conversation record to validate
        expected_split: If provided, verify the conversationId hashes to this split
    """
    errors = []
    warnings = []  # Non-fatal issues
    
    # ===========================================================================
    # 1. REQUIRED FIELDS
    # ===========================================================================
    required_fields = ["conversationId", "userName", "bucket", "turnsArray"]
    for field in required_fields:
        if field not in record or record[field] is None:
            errors.append(f"Missing required field: {field}")
    
    conversation_id = record.get("conversationId", "")
    
    # ===========================================================================
    # 2. SPLIT HASH VERIFICATION (mutual exclusivity guarantee)
    # ===========================================================================
    if expected_split and conversation_id:
        actual_split = get_split(conversation_id)
        if actual_split != expected_split:
            errors.append(f"Split mismatch: expected {expected_split}, hash maps to {actual_split}")
    
    # ===========================================================================
    # 3. TURNS ARRAY VALIDATION
    # ===========================================================================
    turns = record.get("turnsArray", [])
    if not isinstance(turns, list):
        errors.append(f"turnsArray is not a list: {type(turns)}")
    elif len(turns) == 0:
        errors.append("turnsArray is empty")
    else:
        turn_count = len(turns)
        
        # 3a. TURN COUNT MATCHES BUCKET
        bucket = record.get("bucket", "")
        bucket_normalized = _normalize_bucket_name(bucket) if bucket else ""
        if bucket_normalized == "short" and not (3 <= turn_count <= 5):
            errors.append(f"Bucket mismatch: short bucket has {turn_count} turns (expected 3-5)")
        elif bucket_normalized == "medium" and not (6 <= turn_count <= 10):
            errors.append(f"Bucket mismatch: medium bucket has {turn_count} turns (expected 6-10)")
        elif bucket_normalized == "long" and not (11 <= turn_count <= 20):
            errors.append(f"Bucket mismatch: long bucket has {turn_count} turns (expected 11-20)")
        
        # 3b. FIRST TURN STARTS AT INDEX 1 (completeness check)
        first_turn_index = turns[0].get("turnIndex", 0) if turns else 0
        if first_turn_index != 1:
            errors.append(f"Conversation incomplete: first turn has index {first_turn_index} (expected 1)")
        
        # 3c. TURN INDICES ARE SEQUENTIAL
        expected_index = 1
        for i, turn in enumerate(turns):
            turn_index = turn.get("turnIndex", -1)
            if turn_index != expected_index:
                errors.append(f"Turn index gap: expected {expected_index}, got {turn_index}")
                break  # Only report first gap
            expected_index += 1
        
        # 3d. VALIDATE EACH TURN
        for i, turn in enumerate(turns):
            turn_num = i + 1
            
            # Required turn fields
            turn_fields = ["turnIndex", "messageId", "userMessage", "modelMessage", "llmCalls"]
            for field in turn_fields:
                if field not in turn:
                    errors.append(f"Turn {turn_num} missing field: {field}")
            
            # 3e. USER MESSAGE NON-EMPTY
            user_msg = turn.get("userMessage", "")
            if not user_msg or (isinstance(user_msg, str) and len(user_msg.strip()) == 0):
                errors.append(f"Turn {turn_num} has empty userMessage")
            
            # 3f. MODEL MESSAGE NON-EMPTY
            model_msg = turn.get("modelMessage", "")
            if not model_msg or (isinstance(model_msg, str) and len(model_msg.strip()) == 0):
                warnings.append(f"Turn {turn_num} has empty modelMessage (may be tool-only response)")
            
            # 3g. TOKEN SANITY CHECKS
            llm_calls = turn.get("llmCalls", [])
            if llm_calls and len(llm_calls) > 0:
                for j, call in enumerate(llm_calls):
                    prompt_tokens = call.get("promptTokens", 0)
                    completion_tokens = call.get("completionTokens", 0)
                    
                    # promptTokens should be > 0 for valid LLM calls (includes system prompt, history, user message)
                    # promptTokens <= 0 indicates missing/corrupted telemetry
                    if prompt_tokens is not None and prompt_tokens <= 0:
                        warnings.append(f"Turn {turn_num} call {j+1}: suspicious promptTokens={prompt_tokens} (expected > 0)")
                    
                    # completionTokens can be 0 (e.g., tool-only response) but never negative
                    if completion_tokens is not None and completion_tokens < 0:
                        errors.append(f"Turn {turn_num} call {j+1}: invalid negative completionTokens={completion_tokens}")
                    
                    # Check model field exists
                    if "model" not in call:
                        warnings.append(f"Turn {turn_num} call {j+1}: missing model field")
    
    # ===========================================================================
    # 4. BUCKET VALIDATION
    # ===========================================================================
    bucket = record.get("bucket", "")
    # Accept both full names and short names
    valid_buckets = [
        "short_3_to_5_turns", "medium_6_to_10_turns", "long_11_to_20_turns",
        "short", "medium", "long"  # Allow normalized short names too
    ]
    if bucket and bucket not in valid_buckets:
        errors.append(f"Invalid bucket: {bucket}")
    
    return len(errors) == 0, errors


def validate_all_records(records: list, sample_size: int = 5, expected_split: str = None) -> dict:
    """
    Validate all records and return validation summary.
    
    Args:
        records: List of conversation records
        sample_size: Number of sample errors to keep in summary
        expected_split: If provided, verify all records hash to this split
    """
    total = len(records)
    valid_count = 0
    invalid_count = 0
    error_summary = {}
    sample_errors = []
    
    # Track ALL invalid records for post-analysis (not just samples)
    all_invalid_records = []
    
    # Track conversation IDs for duplicate detection
    seen_conversation_ids = set()
    duplicate_count = 0
    
    iterator = tqdm(records, desc="Validating records") if TQDM_AVAILABLE else records
    
    for record in iterator:
        conversation_id = record.get("conversationId", "")
        
        # Check for duplicates
        if conversation_id in seen_conversation_ids:
            duplicate_count += 1
            error_summary["Duplicate conversationId"] = error_summary.get("Duplicate conversationId", 0) + 1
        else:
            seen_conversation_ids.add(conversation_id)
        
        # Validate record
        is_valid, errors = validate_record(record, expected_split=expected_split)
        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1
            for error in errors:
                error_summary[error] = error_summary.get(error, 0) + 1
            
            # Keep sample for quick display
            if len(sample_errors) < sample_size:
                sample_errors.append({
                    "conversationId": conversation_id or "unknown",
                    "errors": errors
                })
            
            # Keep ALL invalid records for post-analysis
            all_invalid_records.append({
                "conversationId": conversation_id or "unknown",
                "bucket": record.get("bucket", "unknown"),
                "turnCount": len(record.get("turnsArray", [])),
                "errors": errors,
                "record": record  # Full record for debugging
            })
    
    return {
        "total": total,
        "valid": valid_count,
        "invalid": invalid_count,
        "valid_percentage": (valid_count / total * 100) if total > 0 else 0,
        "error_summary": error_summary,
        "sample_errors": sample_errors,
        "all_invalid_records": all_invalid_records,  # Full list for post-analysis
        "unique_conversations": len(seen_conversation_ids),
        "duplicate_count": duplicate_count
    }


def validate_cross_split_exclusivity(all_data: dict) -> dict:
    """
    Verify that no conversationId appears in multiple splits.
    This is critical for train/val/test integrity.
    """
    split_conversation_ids = {}
    
    for split, buckets in all_data.items():
        split_conversation_ids[split] = set()
        for bucket, records in buckets.items():
            for record in records:
                conv_id = record.get("conversationId", "")
                if conv_id:
                    split_conversation_ids[split].add(conv_id)
    
    # Check for overlaps
    overlaps = {}
    splits = list(split_conversation_ids.keys())
    
    for i, split1 in enumerate(splits):
        for split2 in splits[i+1:]:
            intersection = split_conversation_ids[split1] & split_conversation_ids[split2]
            if intersection:
                overlaps[f"{split1}-{split2}"] = {
                    "count": len(intersection),
                    "sample": list(intersection)[:5]
                }
    
    return {
        "is_exclusive": len(overlaps) == 0,
        "overlaps": overlaps,
        "split_sizes": {split: len(ids) for split, ids in split_conversation_ids.items()}
    }


def save_invalid_records(validation_result: dict, output_dir: str = ".", split_name: str = "") -> str:
    """
    Save invalid records to a JSON file for post-analysis.
    
    Args:
        validation_result: Result from validate_all_records
        output_dir: Directory to save the file
        split_name: Name of the split (e.g., "train", "val", "test")
    
    Returns:
        Path to the saved file, or None if no invalid records
    """
    invalid_records = validation_result.get('all_invalid_records', [])
    
    if not invalid_records:
        return None
    
    # Create filename with timestamp
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    split_suffix = f"_{split_name}" if split_name else ""
    filename = f"invalid_records{split_suffix}_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)
    
    # Prepare output - exclude full record to keep file size manageable
    output_data = {
        "summary": {
            "total_invalid": len(invalid_records),
            "error_summary": validation_result.get('error_summary', {}),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "split": split_name or "all"
        },
        "invalid_records": [
            {
                "conversationId": r["conversationId"],
                "bucket": r["bucket"],
                "turnCount": r["turnCount"],
                "errors": r["errors"]
                # Note: Full record omitted for file size; can be added if needed
            }
            for r in invalid_records
        ]
    }
    
    # Save to file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, default=str)
    
    return filepath


def print_validation_report(validation_result: dict, split_name: str = "", save_invalid: bool = True):
    """Print a formatted validation report and optionally save invalid records."""
    print(f"\n{'='*60}")
    print("DATA VALIDATION REPORT")
    print(f"{'='*60}")
    print(f"Total records:         {validation_result['total']:,}")
    print(f"Valid records:         {validation_result['valid']:,} ({validation_result['valid_percentage']:.1f}%)")
    print(f"Invalid records:       {validation_result['invalid']:,}")
    print(f"Unique conversations:  {validation_result.get('unique_conversations', 'N/A'):,}")
    print(f"Duplicates found:      {validation_result.get('duplicate_count', 0):,}")
    
    if validation_result['error_summary']:
        print(f"\n⚠️  Error Summary:")
        for error, count in sorted(validation_result['error_summary'].items(), key=lambda x: -x[1])[:10]:
            print(f"  • {error}: {count}")
        if len(validation_result['error_summary']) > 10:
            print(f"  ... and {len(validation_result['error_summary']) - 10} more error types")
    
    if validation_result['sample_errors']:
        print(f"\n📋 Sample Invalid Records:")
        for sample in validation_result['sample_errors'][:3]:
            print(f"  • {sample['conversationId'][:40]}...: {sample['errors'][:2]}")
    
    # Save invalid records for post-analysis
    if save_invalid and validation_result['invalid'] > 0:
        invalid_file = save_invalid_records(validation_result, split_name=split_name)
        if invalid_file:
            print(f"\n📁 Invalid records saved to: {invalid_file}")
    
    print(f"{'='*60}\n")
    
    return validation_result['valid_percentage'] >= 95  # Consider 95%+ as passing


def print_cross_split_report(exclusivity_result: dict):
    """Print cross-split exclusivity report."""
    print(f"\n{'='*60}")
    print("CROSS-SPLIT EXCLUSIVITY CHECK")
    print(f"{'='*60}")
    
    print(f"\nSplit sizes:")
    for split, size in exclusivity_result['split_sizes'].items():
        print(f"  • {split}: {size:,} unique conversations")
    
    if exclusivity_result['is_exclusive']:
        print(f"\n✅ PASSED: No conversation appears in multiple splits")
    else:
        print(f"\n❌ FAILED: Found overlapping conversations!")
        for overlap_key, overlap_info in exclusivity_result['overlaps'].items():
            print(f"  • {overlap_key}: {overlap_info['count']} overlapping conversations")
            print(f"    Sample: {overlap_info['sample'][:3]}")
    
    print(f"{'='*60}\n")
    
    return exclusivity_result['is_exclusive']


# =============================================================================
# DATA PROCESSING
# =============================================================================

def split_by_bucket_and_split(results: list) -> dict:
    """Split results by split (train/val/test) and bucket."""
    data = {
        split: {
            "short_3_to_5_turns": [],
            "medium_6_to_10_turns": [],
            "long_11_to_20_turns": []
        }
        for split in SPLITS
    }
    
    for record in results:
        bucket = record.get("bucket", "")
        split = record.get("split", get_split(record.get("conversationId", "")))
        
        if "short" in bucket:
            data[split]["short_3_to_5_turns"].append(record)
        elif "medium" in bucket:
            data[split]["medium_6_to_10_turns"].append(record)
        elif "long" in bucket:
            data[split]["long_11_to_20_turns"].append(record)
    
    return data


def create_metadata(is_test: bool, data: dict, time_window_days: int) -> dict:
    """Create metadata JSON for the export."""
    now = datetime.utcnow()
    
    # Calculate counts
    counts = {}
    grand_total = 0
    for split in SPLITS:
        counts[split] = {}
        split_total = 0
        for bucket in data[split]:
            count = len(data[split][bucket])
            counts[split][bucket] = count
            split_total += count
        counts[split]["total"] = split_total
        grand_total += split_total
    counts["grand_total"] = grand_total
    
    size_label = "test120" if is_test else "120k"
    mode = "test" if is_test else "production"
    
    metadata = {
        "curation_info": {
            "curation_date": now.isoformat() + "Z",
            "curation_id": f"vscodedata_{size_label}_complete_stratified_deduped_{time_window_days}d_{now.strftime('%Y%m%d')}",
            "query_file": "sft_test_100_lite.kql" if is_test else "sft_100k_production_with_splits.kql",
            "data_source": "vscode_1p_agent_mode",
            "is_test": is_test
        },
        "query_parameters": {
            "time_window": f"ago({time_window_days}d) to now()",
            "time_window_start": (now - timedelta(days=time_window_days)).isoformat() + "Z",
            "time_window_end": now.isoformat() + "Z",
            "cluster": KUSTO_CLUSTER,
            "database": KUSTO_DATABASE
        },
        "completeness_criteria": {
            "minTurnIndex_equals": 1,
            "capturedTurnCount_equals_maxTurnIndex": True,
            "mode": "agent"
        },
        "deduplication": {
            "method": "arg_max(strlen(messageText)) by conversationId, messageId, source",
            "description": "Keep longest message text for each (conversationId, messageId, source) triple"
        },
        "split_ratios": SPLIT_RATIOS,
        "split_method": {
            "algorithm": "hash(conversationId) % 100",
            "train_range": "hash < 80",
            "val_range": "80 <= hash < 90",
            "test_range": "hash >= 90",
            "mutual_exclusivity": "Guaranteed by deterministic hash-based partitioning"
        },
        "stratification": {
            "buckets": {
                "short_3_to_5_turns": {"turn_range": [3, 5]},
                "medium_6_to_10_turns": {"turn_range": [6, 10]},
                "long_11_to_20_turns": {"turn_range": [11, 20]}
            },
            "target_counts": SAMPLE_SIZES[mode]
        },
        "actual_counts": counts,
        "output_structure": {
            "train": ["short_3_to_5_turns.json", "medium_6_to_10_turns.json", "long_11_to_20_turns.json"],
            "val": ["short_3_to_5_turns.json", "medium_6_to_10_turns.json", "long_11_to_20_turns.json"],
            "test": ["short_3_to_5_turns.json", "medium_6_to_10_turns.json", "long_11_to_20_turns.json"]
        }
    }
    
    return metadata


# =============================================================================
# MAIN EXPORT FUNCTION
# =============================================================================

def export_sft_data(is_test: bool = False, target_split: str = None, dry_run: bool = False):
    """
    Main function to export SFT data to Azure Blob Storage.
    
    Args:
        is_test: If True, run test query (~100 records) instead of production
        target_split: If specified, only export this split (train/val/test)
        dry_run: If True, only run query without uploading to blob
    """
    
    # Configuration
    if is_test:
        query_file = TEST_QUERY_FILE
        time_window_days = 6  # 6 hours converted to fraction of days
        size_label = "test120"
        print("=" * 70)
        print("RUNNING TEST MODE (~120 records, 6 hour window)")
        print("=" * 70)
    else:
        query_file = PROD_QUERY_FILE
        time_window_days = 60
        size_label = "120k"
        print("=" * 70)
        print("RUNNING PRODUCTION MODE (~120k records, 60 day window)")
        print("=" * 70)
    
    # Determine which splits to export
    splits_to_export = [target_split] if target_split else SPLITS
    print(f"Splits to export: {splits_to_export}")
    
    # Read base query
    print(f"\nReading query from: {query_file}")
    with open(query_file, 'r') as f:
        base_query = f.read()
    
    # Connect to services
    print("\nConnecting to Kusto...")
    kusto_client = get_kusto_client()
    
    print("Connecting to Blob Storage...")
    blob_service_client = get_blob_service_client()
    
    # Collect all results
    all_data = {
        split: {"short_3_to_5_turns": [], "medium_6_to_10_turns": [], "long_11_to_20_turns": []}
        for split in SPLITS
    }
    
    # For test mode, run single query and split locally
    if is_test:
        print("\nRunning test query...")
        results = run_kusto_query(kusto_client, base_query)
        
        # =====================================================================
        # TOKEN VALIDATION (early detection of query bugs)
        # =====================================================================
        if results:
            print("\n🔍 Validating token data...")
            try:
                token_validation = validate_chunk_tokens(results, chunk_num=0)
                
                if token_validation["invalid"] > 0:
                    print(f"\n   ⚠️  TOKEN VALIDATION WARNING:")
                    print(f"      • Valid records: {token_validation['valid']:,}")
                    print(f"      • Invalid records: {token_validation['invalid']:,} ({token_validation['invalid_percentage']:.1f}%)")
                    if token_validation["sample_errors"]:
                        print(f"      • Sample errors:")
                        for err in token_validation["sample_errors"][:3]:
                            print(f"        - {err}")
                    
                    if token_validation["is_critical"]:
                        print(f"\n   🚨 CRITICAL: >10% of records have token issues!")
                else:
                    print(f"   ✅ Token validation passed ({token_validation['valid']:,} records)")
                    
            except TokenValidationError as e:
                # ALL records have token issues - this is a query bug, fail fast!
                print(f"\n{'='*70}")
                print(f"🚨 CRITICAL TOKEN VALIDATION FAILURE")
                print(f"{'='*70}")
                print(str(e))
                print(f"{'='*70}")
                raise
        
        # Assign splits based on hash
        for record in results:
            split = get_split(record.get("conversationId", ""))
            record["split"] = split
            bucket = record.get("bucket", "")
            
            if "short" in bucket:
                all_data[split]["short_3_to_5_turns"].append(record)
            elif "medium" in bucket:
                all_data[split]["medium_6_to_10_turns"].append(record)
            elif "long" in bucket:
                all_data[split]["long_11_to_20_turns"].append(record)
    else:
        # For production with chunking: gather ALL candidates, then sample in Python
        if ENABLE_CHUNKING and time_window_days >= 10:
            print(f"\n{'='*70}")
            print("CHUNKED AGGREGATION MODE")
            print(f"{'='*70}")
            
            if CHUNKING_METHOD == "hash":
                # RECOMMENDED: Hash-based chunking guarantees conversation completeness
                print("Method: HASH-BASED CHUNKING (Recommended)")
                print("  ✅ Guarantees: Each conversation fully in ONE chunk")
                print("  ✅ Guarantees: Conversation completeness preserved")
                print("Strategy: Gather ALL candidates via hash chunks, then stratified sample in Python")
                
                all_candidates = run_hash_chunked_query(kusto_client, num_chunks=NUM_HASH_CHUNKS)
            
            else:
                # Legacy: Time-based chunking (may split conversations)
                print("Method: TIME-BASED CHUNKING (Legacy)")
                print("  ⚠️  Warning: Conversations may be split across chunks")
                print("Strategy: Gather ALL candidates via time chunks, then stratified sample in Python")
                
                candidates_query_file = CANDIDATES_QUERY_FILE
                print(f"\nReading candidates query from: {candidates_query_file}")
                with open(candidates_query_file, 'r') as f:
                    candidates_query = f.read()
                
                print(f"\nGathering candidates ({time_window_days} days / {CHUNK_DAYS} day chunks)...")
                all_candidates = run_chunked_query(
                    kusto_client, 
                    candidates_query, 
                    total_days=time_window_days, 
                    chunk_days=CHUNK_DAYS
                )
            
            print(f"\n📊 Total candidates gathered: {len(all_candidates):,}")
            
            # Perform stratified sampling in Python
            sample_sizes = SAMPLE_SIZES["production"]
            sampled_data = stratified_sample_in_python(all_candidates, sample_sizes)
            
            # Map to the expected structure with full bucket names
            for split in splits_to_export:
                all_data[split]["short_3_to_5_turns"] = sampled_data[split]["short"]
                all_data[split]["medium_6_to_10_turns"] = sampled_data[split]["medium"]
                all_data[split]["long_11_to_20_turns"] = sampled_data[split]["long"]
        
        else:
            # Non-chunked mode: run query for each split separately
            total_splits = len(splits_to_export)
            for i, split in enumerate(splits_to_export, 1):
                print(f"\n{'='*70}")
                print(f"SPLIT {i}/{total_splits}: {split.upper()}")
                print(f"{'='*70}")
                
                query = modify_query_for_split(base_query, split)
                
                try:
                    results = run_kusto_query(kusto_client, query)
                    
                    for record in results:
                        bucket = record.get("bucket", "")
                        if "short" in bucket:
                            all_data[split]["short_3_to_5_turns"].append(record)
                        elif "medium" in bucket:
                            all_data[split]["medium_6_to_10_turns"].append(record)
                        elif "long" in bucket:
                            all_data[split]["long_11_to_20_turns"].append(record)
                    
                    # Progress summary
                    total = sum(len(all_data[split][b]) for b in all_data[split])
                    print(f"\n✅ {split.upper()} complete: {total:,} records")
                    
                except Exception as e:
                    print(f"\n❌ FAILED to export {split.upper()} split")
                    print(f"   Error: {e}")
                    print(f"\n   You can resume by running:")
                    print(f"   python export_sft_to_blob.py --split {split}")
                    raise
    
    # Print summary
    print("\n" + "=" * 70)
    print("DATA SUMMARY")
    print("=" * 70)
    for split in splits_to_export:
        print(f"\n{split.upper()}:")
        for bucket, records in all_data[split].items():
            print(f"  {bucket}: {len(records):,} records")
    
    # Validate all records
    print("\n" + "=" * 70)
    print("VALIDATING DATA")
    print("=" * 70)
    
    # Validate each split separately (with split hash verification)
    all_validation_passed = True
    for split in splits_to_export:
        split_records = []
        for bucket, records in all_data[split].items():
            split_records.extend(records)
        
        if split_records:
            print(f"\n📊 Validating {split.upper()} split ({len(split_records):,} records)...")
            validation_result = validate_all_records(split_records, expected_split=split)
            validation_passed = print_validation_report(validation_result, split_name=split)
            
            if not validation_passed:
                all_validation_passed = False
    
    # Cross-split exclusivity check (only if multiple splits)
    if len(splits_to_export) > 1:
        exclusivity_result = validate_cross_split_exclusivity(all_data)
        exclusivity_passed = print_cross_split_report(exclusivity_result)
        
        if not exclusivity_passed:
            print("❌ CRITICAL: Cross-split contamination detected!")
            print("   This will invalidate your train/val/test splits.")
            # Don't fail - let user decide
    
    if not all_validation_passed:
        print("⚠️  WARNING: Some validation checks had <95% pass rate")
        print("   Continuing with upload anyway...")
    
    # Create metadata
    metadata = create_metadata(is_test, all_data, time_window_days if not is_test else 1)
    
    # Generate blob path with full timestamp to avoid accidental overrides
    now = datetime.utcnow()
    timestamp = now.strftime('%Y%m%d_%H%M%S')  # e.g., 20241209_143052
    folder_name = f"vscodedata_{size_label}_complete_stratified_deduped_{time_window_days}d_{timestamp}"
    blob_folder = f"{BLOB_BASE_PATH}/{folder_name}"
    
    # Skip upload in dry-run mode
    if dry_run:
        print(f"\n" + "=" * 70)
        print("DRY RUN - SKIPPING BLOB UPLOAD")
        print("=" * 70)
        print(f"✅ Query succeeded! Would upload to: {blob_folder}/")
        print(f"\nThis test shows OOM is NOT a problem for the full query.")
        print(f"Re-run without --dry-run to actually upload data.")
        
        # Print final summary
        print("\n" + "=" * 70)
        print("DRY RUN COMPLETE")
        print("=" * 70)
        print(f"Total records fetched: {metadata['actual_counts']['grand_total']:,}")
        for split in splits_to_export:
            total = metadata['actual_counts'][split]['total']
            print(f"  {split}: {total:,} records")
        return metadata
    
    print(f"\n" + "=" * 70)
    print("UPLOADING TO BLOB STORAGE")
    print("=" * 70)
    print(f"Container: {STORAGE_CONTAINER}")
    print(f"Path: {blob_folder}/")
    
    # Upload each split's data
    upload_tasks = []
    for split in splits_to_export:
        for bucket, records in all_data[split].items():
            if records:  # Only upload if there's data
                upload_tasks.append((split, bucket, records))
    
    print(f"\nUploading {len(upload_tasks)} files...")
    
    if TQDM_AVAILABLE:
        for split, bucket, records in tqdm(upload_tasks, desc="Uploading"):
            blob_path = f"{blob_folder}/{split}/{bucket}.json"
            upload_json_to_blob(blob_service_client, STORAGE_CONTAINER, blob_path, records)
    else:
        for i, (split, bucket, records) in enumerate(upload_tasks, 1):
            print(f"  [{i}/{len(upload_tasks)}] {split}/{bucket}...")
            blob_path = f"{blob_folder}/{split}/{bucket}.json"
            upload_json_to_blob(blob_service_client, STORAGE_CONTAINER, blob_path, records)
    
    # Upload metadata
    print("\nUploading metadata...")
    metadata_path = f"{blob_folder}/metadata.json"
    upload_json_to_blob(blob_service_client, STORAGE_CONTAINER, metadata_path, metadata)
    
    # Print final summary
    print("\n" + "=" * 70)
    print("EXPORT COMPLETE")
    print("=" * 70)
    print(f"Total records: {metadata['actual_counts']['grand_total']:,}")
    print(f"Location: {STORAGE_ACCOUNT_URL}/{STORAGE_CONTAINER}/{blob_folder}/")
    print("\nStructure:")
    for split in splits_to_export:
        total = metadata['actual_counts'][split]['total']
        print(f"  {split}/ ({total:,} records)")
        for bucket in all_data[split]:
            count = len(all_data[split][bucket])
            print(f"    └── {bucket}.json ({count:,})")
    print(f"  metadata.json")
    
    return metadata


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Export SFT conversation data from Kusto to Azure Blob Storage"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run with test query (~120 records) instead of production (~120k)"
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "test"],
        help="Export only this split. If not specified, exports all splits."
    )
    parser.add_argument(
        "--no-chunking",
        action="store_true",
        help="Disable time-based chunking. Runs a single query for full time window. "
             "May cause OOM for large time windows."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only run the query without uploading to blob. For testing OOM behavior."
    )
    
    args = parser.parse_args()
    
    # Check Azure login
    print("Checking Azure authentication...")
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token("https://management.azure.com/.default")
        print("Azure authentication OK")
    except Exception as e:
        print(f"ERROR: Azure authentication failed. Please run 'az login' first.")
        print(f"Details: {e}")
        return 1
    
    # Override chunking if requested
    if args.no_chunking:
        global ENABLE_CHUNKING
        ENABLE_CHUNKING = False
        print("⚠️  Chunking DISABLED - running single full-window query")
    
    # Run export
    try:
        export_sft_data(is_test=args.test, target_split=args.split, dry_run=args.dry_run)
        return 0
    except Exception as e:
        print(f"ERROR: Export failed: {e}")
        raise


if __name__ == "__main__":
    exit(main())
