#!/usr/bin/env python3
"""Extract a PDF to Markdown with Docling.  Usage: 1_extract.py document.pdf [output.md]"""

import os
import sys

from docling.document_converter import DocumentConverter


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit("Usage: python scripts/1_extract.py document.pdf [output.md]")
    pdf = sys.argv[1]
    if not os.path.exists(pdf):
        sys.exit("PDF not found: " + pdf)
    md_path = sys.argv[2] if len(sys.argv) == 3 else os.path.splitext(pdf)[0] + ".md"

    print(f"Extracting {pdf} -> {md_path}")
    markdown = DocumentConverter().convert(pdf).document.export_to_markdown()
    with open(md_path, "w") as f:
        f.write(markdown)
    print(f"Wrote {len(markdown):,} characters to {md_path}")


if __name__ == "__main__":
    main()
