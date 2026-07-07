#!/usr/bin/env python3
"""
2_chunk.py — split a Markdown file into chunks and write them to CSV.

Uses Docling's HybridChunker (structure- and token-aware), capped to the
embedding model's token limit. The output is a simple two-column CSV:

    chunk_id, chunk_text

which you can open in a spreadsheet to see exactly what will be indexed, then
hand to 4_ingest.sql.

Usage:  python scripts/2_chunk.py document.md [chunks.csv]
        (default output: the .md path with a .chunks.csv extension)
Config (optional, via .env): MAX_TOKENS, TOKENIZER_MODEL.
"""

import csv
import os
import sys

from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from transformers import AutoTokenizer

# Optional config from .env. The token budget should match the embedding model
# you'll use in 4_ingest.sql (default: all-MiniLM-L6-v2, 256 tokens).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _env in (os.path.join(_ROOT, ".env"), ".env"):
    if os.path.exists(_env):
        for _line in open(_env):
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

TOKENIZER  = os.environ.get("TOKENIZER_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "256"))


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: python scripts/2_chunk.py document.md [chunks.csv]")
    md_path = sys.argv[1]
    if not os.path.exists(md_path):
        sys.exit("Markdown not found: " + md_path)
    csv_path = sys.argv[2] if len(sys.argv) == 3 else os.path.splitext(md_path)[0] + ".chunks.csv"

    print(f"Chunking {md_path} (max {MAX_TOKENS} tokens)")
    document = DocumentConverter().convert(md_path).document
    chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(TOKENIZER), max_tokens=MAX_TOKENS))
    # contextualize() prepends each chunk's heading trail, so a chunk carries
    # the section it came from.
    chunks = [chunker.contextualize(chunk=c) for c in chunker.chunk(dl_doc=document)]

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["chunk_id", "chunk_text"])
        for chunk_id, text in enumerate(chunks, start=1):
            writer.writerow([chunk_id, text])
    print(f"Wrote {len(chunks)} chunks to {csv_path}")


if __name__ == "__main__":
    main()
