#!/bin/bash
# Sequential model benchmark (CPU). Logs in logs/
cd "$(dirname "$0")"
PY=.venv/Scripts/python
for m in intfloat/multilingual-e5-small distilbert/distilbert-base-multilingual-cased google/muril-base-cased FacebookAI/xlm-roberta-base; do
  n=$(basename $m)
  $PY -m app.training.finetune_transformer --model $m --epochs 4 > logs/$n.log 2>&1
done
$PY -m app.training.finetune_transformer --model intfloat/multilingual-e5-small --epochs 4 --ctx > logs/e5-small-ctx.log 2>&1
