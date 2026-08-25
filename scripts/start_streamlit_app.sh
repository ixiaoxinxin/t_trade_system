#!/bin/zsh
set -e

PROJECT_DIR="/Users/xiaoxinxin/t_trade_system"
PYTHON_BIN="/opt/miniconda3/bin/python"
PORT="8501"
HOST="127.0.0.1"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/logs"

"$PYTHON_BIN" scheduled_refresh.py --daemon \
  >> "$PROJECT_DIR/logs/scheduled_refresh.launch.log" 2>&1 &

exec "$PYTHON_BIN" -m streamlit run app.py \
  --server.port "$PORT" \
  --server.address "$HOST" \
  --server.headless true
