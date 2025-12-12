#!/bin/bash
# Run SFT export script in tmux session with logging

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
LOG_DIR="$SCRIPT_DIR"
LOG_FILE="$LOG_DIR/export_log_$(date +%Y%m%d_%H%M%S).log"
SCRIPT_PATH="$SCRIPT_DIR/export_sft_to_blob.py"
VENV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/venv"
TMUX_SESSION="sft_export"

echo "=========================================="
echo "SFT Export - Tmux Session Setup"
echo "=========================================="
echo "Script: $SCRIPT_PATH"
echo "Log file: $LOG_FILE"
echo "Tmux session: $TMUX_SESSION"
echo ""

# Check if tmux session already exists
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "⚠️  Tmux session '$TMUX_SESSION' already exists!"
    echo "   Attach with: tmux attach -t $TMUX_SESSION"
    echo "   Or kill it first: tmux kill-session -t $TMUX_SESSION"
    exit 1
fi

# Check if script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ Error: Script not found at $SCRIPT_PATH"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "⚠️  Virtual environment not found at $VENV_DIR"
    echo "   Please run setup_env.sh first:"
    echo "   cd $(dirname "$VENV_DIR") && ./setup_env.sh"
    exit 1
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ Error: Python not found in virtual environment at $VENV_PYTHON"
    exit 1
fi

# Create tmux session and run script with logging
echo "Creating tmux session and starting export..."
echo "Using Python: $VENV_PYTHON"
tmux new-session -d -s "$TMUX_SESSION" -c "$PROJECT_ROOT" \
    "source '$VENV_DIR/bin/activate' && \
     '$VENV_PYTHON' '$SCRIPT_PATH' 2>&1 | tee -a '$LOG_FILE'; \
     echo ''; \
     echo '=========================================='; \
     echo 'Script completed. Log saved to:'; \
     echo '$LOG_FILE'; \
     echo '=========================================='; \
     echo ''; \
     echo 'Press Ctrl+C to close this window...'; \
     sleep 3600"

# Wait a moment for session to start
sleep 1

# Check if session was created successfully
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "✅ Tmux session created successfully!"
    echo ""
    echo "To attach to the session:"
    echo "  tmux attach -t $TMUX_SESSION"
    echo ""
    echo "To detach (keep running):"
    echo "  Press Ctrl+B, then D"
    echo ""
    echo "To view logs in real-time:"
    echo "  tail -f '$LOG_FILE'"
    echo ""
    echo "Log file location:"
    echo "  $LOG_FILE"
    echo ""
    echo "Attaching now (press Ctrl+B then D to detach)..."
    sleep 2
    tmux attach -t "$TMUX_SESSION"
else
    echo "❌ Failed to create tmux session"
    exit 1
fi

