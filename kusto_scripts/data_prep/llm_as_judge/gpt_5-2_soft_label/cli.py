"""
CLI Module
==========

Command-line interface for the soft-label teacher pipeline.

This module provides a user-friendly CLI with subcommands for:
    - label: Run the labeling pipeline on a JSONL dataset
    - info: Show configuration and tokenizer info
    - test: Test API connectivity with a sample message

Usage Examples:

    # Label a dataset (rationales enabled by default)
    python -m gpt_5-2_soft_label label \\
        --input data.jsonl \\
        --output labeled.jsonl \\
        --model gpt-5.2

    # Label WITHOUT rationales (faster, cheaper)
    python -m gpt_5-2_soft_label label \\
        --input data.jsonl \\
        --output labeled.jsonl \\
        --model gpt-5.2 \\
        --no-rationales

    # Show configuration info
    python -m gpt_5-2_soft_label info --model gpt-5.2

    # Test API connectivity
    python -m gpt_5-2_soft_label test --model gpt-5.2 --message "How do I sort a list?"

Environment Variables:
    AZURE_OPENAI_API_KEY     : API key (optional if using Key Vault)
    AZURE_OPENAI_ENDPOINT    : Endpoint URL (optional, has default)
    AZURE_OPENAI_API_VERSION : API version (optional, has default)
"""

import argparse
import asyncio
import sys
from typing import Optional

from .config import (
    DEFAULT_MODEL,
    DEFAULT_CONCURRENCY,
    DEFAULT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    KEYVAULT_NAME,
    KEYVAULT_SECRET_NAME,
    RATE_LIMIT_REQUESTS_PER_MINUTE,
    RATE_LIMIT_TOKENS_PER_MINUTE,
)
from .strategies import STRATEGIES


def create_parser() -> argparse.ArgumentParser:
    """
    Create the argument parser with all subcommands.
    
    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        prog="gpt_5-2_soft_label",
        description="GPT-5.2 Soft Label Teacher - Binary classification with soft labels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Label a dataset (rationales enabled by default)
  python -m gpt_5-2_soft_label label --input data.jsonl --output labeled.jsonl

  # Label WITHOUT rationales (faster, cheaper)
  python -m gpt_5-2_soft_label label --input data.jsonl --output labeled.jsonl --no-rationales

  # Show configuration
  python -m gpt_5-2_soft_label info

  # Test API connectivity
  python -m gpt_5-2_soft_label test --message "How do I create a Python class?"
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # =========================================================================
    # LABEL command
    # =========================================================================
    label_parser = subparsers.add_parser(
        "label",
        help="Label a JSONL dataset with soft labels",
        description="Process a JSONL file, adding hard_label, soft_label, and rationale to each turn.",
    )
    
    label_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to input JSONL file (conversations)",
    )
    
    label_parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to output JSONL file (labeled turns)",
    )
    
    label_parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Azure deployment name (default: {DEFAULT_MODEL})",
    )
    
    label_parser.add_argument(
        "--strategy", "-s",
        default="user_message_only",
        choices=list(STRATEGIES.keys()),
        help="Labeling strategy - what the LLM sees (default: user_message_only)",
    )
    
    label_parser.add_argument(
        "--no-rationales",
        action="store_true",
        help="Disable rationale generation (faster, cheaper)",
    )
    
    label_parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max concurrent API calls (default: {DEFAULT_CONCURRENCY})",
    )
    
    label_parser.add_argument(
        "--no-keyvault",
        action="store_true",
        help="Skip Key Vault, use AZURE_OPENAI_API_KEY env var only",
    )
    
    # =========================================================================
    # INFO command
    # =========================================================================
    info_parser = subparsers.add_parser(
        "info",
        help="Show configuration and tokenizer info",
        description="Display current configuration, tokenizer details, and API settings.",
    )
    
    info_parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Model to show tokenizer info for (default: {DEFAULT_MODEL})",
    )
    
    # =========================================================================
    # TEST command
    # =========================================================================
    test_parser = subparsers.add_parser(
        "test",
        help="Test API connectivity with a sample message",
        description="Send a test classification request to verify API connectivity.",
    )
    
    test_parser.add_argument(
        "--message",
        default="How do I create a list in Python?",
        help="Message to classify (default: simple Python question)",
    )
    
    test_parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Azure deployment name (default: {DEFAULT_MODEL})",
    )
    
    test_parser.add_argument(
        "--no-rationale",
        action="store_true",
        help="Skip rationale generation",
    )
    
    test_parser.add_argument(
        "--no-keyvault",
        action="store_true",
        help="Skip Key Vault, use AZURE_OPENAI_API_KEY env var only",
    )
    
    return parser


async def cmd_label(args: argparse.Namespace) -> int:
    """
    Execute the label command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from .client import get_azure_openai_client
    from .pipeline import label_dataset
    
    with_rationales = not args.no_rationales
    
    print("=" * 60)
    print("GPT-5.2 SOFT LABEL TEACHER")
    print("=" * 60)
    print(f"Input:          {args.input}")
    print(f"Output:         {args.output}")
    print(f"Model:          {args.model}")
    print(f"Strategy:       {args.strategy}")
    print(f"Rationales:     {'enabled (default)' if with_rationales else 'disabled'}")
    print(f"Concurrency:    {args.concurrency}")
    print()
    
    try:
        # Get client
        print("Connecting to Azure OpenAI...")
        client = get_azure_openai_client(use_keyvault=not args.no_keyvault)
        print("✓ Connected\n")
        
        # Run pipeline
        stats = await label_dataset(
            client=client,
            input_path=args.input,
            output_path=args.output,
            model=args.model,
            strategy_name=args.strategy,
            with_rationales=with_rationales,
            concurrency=args.concurrency,
        )
        
        if stats.failed > 0:
            print(f"\n⚠ Warning: {stats.failed} turns failed to label")
            return 1 if stats.failed == stats.total else 0
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_info(args: argparse.Namespace) -> int:
    """
    Execute the info command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Exit code (0 for success)
    """
    from .tokenizer import get_label_token_ids
    from .config import (
        CLASSIFICATION_MAX_TOKENS,
        CLASSIFICATION_TEMPERATURE,
        DEFAULT_LOGIT_BIAS,
        MAX_RETRIES,
        RETRY_MIN_WAIT,
        RETRY_MAX_WAIT,
    )
    
    print("=" * 60)
    print("GPT-5.2 SOFT LABEL TEACHER - CONFIGURATION")
    print("=" * 60)
    
    print("\nAPI Settings:")
    print(f"  Endpoint:         {AZURE_OPENAI_ENDPOINT}")
    print(f"  API Version:      {DEFAULT_API_VERSION}")
    print(f"  Key Vault:        {KEYVAULT_NAME}")
    print(f"  Secret:           {KEYVAULT_SECRET_NAME}")
    
    print("\nRate Limits (gpt-5.2 deployment):")
    print(f"  Requests/min:     {RATE_LIMIT_REQUESTS_PER_MINUTE:,}")
    print(f"  Tokens/min:       {RATE_LIMIT_TOKENS_PER_MINUTE:,}")
    print(f"  Concurrency:      {DEFAULT_CONCURRENCY} (semaphore)")
    
    print("\nRetry Configuration (tenacity):")
    print(f"  Max retries:      {MAX_RETRIES}")
    print(f"  Min wait:         {RETRY_MIN_WAIT}s")
    print(f"  Max wait:         {RETRY_MAX_WAIT}s")
    
    print("\nClassification Parameters:")
    print(f"  max_tokens:       {CLASSIFICATION_MAX_TOKENS}")
    print(f"  temperature:      {CLASSIFICATION_TEMPERATURE}")
    print(f"  logit_bias:       +{DEFAULT_LOGIT_BIAS} (exp({DEFAULT_LOGIT_BIAS}) ≈ {2.718**DEFAULT_LOGIT_BIAS:.0f}x odds)")
    
    print(f"\nTokenizer Info (model: {args.model}):")
    try:
        tokenizer = get_label_token_ids(model=args.model)
        print(f"  Encoding:         {tokenizer.encoding_name}")
        print(f"  Token '0':        ID {tokenizer.token_id_0}")
        print(f"  Token '1':        ID {tokenizer.token_id_1}")
        print(f"  Verified:         {tokenizer.verified}")
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\nAvailable Strategies:")
    for name, cls in STRATEGIES.items():
        strategy = cls()
        print(f"  {name}: {strategy.description[:60]}...")
    
    print("\nLabel Semantics:")
    print("  0 = REQUIRES reasoning (complex, multi-step)")
    print("  1 = Does NOT require reasoning (simple, pattern-matching)")
    
    print("\nOutput Schema (minimal):")
    print("  conversationId, messageId, hard_label, soft_label, rationale")
    
    print("=" * 60)
    return 0


async def cmd_test(args: argparse.Namespace) -> int:
    """
    Execute the test command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from .client import get_azure_openai_client
    from .tokenizer import get_label_token_ids
    from .classifier import classify_message
    from .rationale import generate_rationale
    
    print("=" * 60)
    print("GPT-5.2 SOFT LABEL TEACHER - API TEST")
    print("=" * 60)
    print(f"Model:   {args.model}")
    print(f"Message: {args.message[:50]}..." if len(args.message) > 50 else f"Message: {args.message}")
    print()
    
    try:
        # Get client and tokenizer
        print("Connecting to Azure OpenAI...")
        client = get_azure_openai_client(use_keyvault=not args.no_keyvault)
        tokenizer = get_label_token_ids(model=args.model)
        print("✓ Connected\n")
        
        # Classify
        print("Running classification...")
        result = await classify_message(
            client=client,
            user_message=args.message,
            model=args.model,
            tokenizer=tokenizer,
        )
        
        print("\nClassification Result:")
        print(f"  Hard label:      {result.hard_label}")
        print(f"  Soft label:      {result.soft_label:.4f}")
        print(f"  Confidence:      {result.confidence:.4f}")
        print(f"  Raw P('0'):      {result.raw_prob_0:.4f}")
        print(f"  Raw P('1'):      {result.raw_prob_1:.4f}")
        print(f"  Generated:       '{result.generated_token}'")
        print(f"  Fallback used:   {result.fallback_used}")
        
        label_meaning = "REQUIRES reasoning" if result.hard_label == 0 else "Does NOT require reasoning"
        print(f"\n  Interpretation: {label_meaning}")
        
        # Generate rationale (default: enabled)
        if not args.no_rationale:
            print("\nGenerating rationale...")
            rationale = await generate_rationale(
                client=client,
                user_message=args.message,
                model=args.model,
                label=result.hard_label,
            )
            print(f"\nRationale:\n  {rationale}")
        
        print("\n" + "=" * 60)
        print("✓ API test successful!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main(argv: Optional[list] = None) -> int:
    """
    Main entry point for the CLI.
    
    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if args.command is None:
        parser.print_help()
        return 0
    
    if args.command == "label":
        return asyncio.run(cmd_label(args))
    elif args.command == "info":
        return cmd_info(args)
    elif args.command == "test":
        return asyncio.run(cmd_test(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
