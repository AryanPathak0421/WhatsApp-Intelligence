#!/bin/sh
# One-off, run with internet access: downloads PUBLIC model weights into the `models` volume.
# After this the AI engine runs fully offline (HF_HUB_OFFLINE=1). No chat data is involved.
set -eu
pip install --no-cache-dir -q "huggingface_hub>=0.24"
python - <<'PY'
import os
from huggingface_hub import snapshot_download
models = [os.environ.get("EMBED_MODEL", "intfloat/multilingual-e5-small")]
# optional extras used by the linker / benchmarks:
# models += ["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"]
for m in models:
    if m == "hashing":
        continue
    print("fetching", m)
    snapshot_download(m, allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "tokenizer*", "sentencepiece*"])
print("done")
PY
