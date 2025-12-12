"""
Package Entry Point
===================

Enables running the package as a module:

    python -m gpt_5-2_soft_label [command] [options]

Commands:
    label   - Label a JSONL dataset with soft labels
    info    - Show configuration and tokenizer info
    test    - Test API connectivity with a sample message

Example:
    python -m gpt_5-2_soft_label label \\
        --input data.jsonl \\
        --output labeled.jsonl \\
        --model gpt-5.2 \\
        --with-rationales
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())

