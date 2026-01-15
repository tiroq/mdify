# mdify-runtime container
# Contains Docling and ML dependencies for document conversion
#
# Build:
#   docker build -t ghcr.io/tiroq/mdify-runtime:latest runtime/
#
# Run:
#   docker run --rm \
#     -v /path/to/input:/work/in:ro \
#     -v /path/to/output:/work/out \
#     ghcr.io/tiroq/mdify-runtime:latest \
#     --in /work/in/file.pdf --out /work/out/file.md

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/tiroq/mdify"
LABEL org.opencontainers.image.description="mdify document conversion runtime with Docling"
LABEL org.opencontainers.image.licenses="MIT"

# Install system dependencies for Docling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpoppler-cpp-dev \
    poppler-utils \
    tesseract-ocr \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Create work directories
RUN mkdir -p /work/in /work/out

# Install Python dependencies
RUN pip install --no-cache-dir docling>=1.0.0

# Copy conversion script
COPY convert.py /app/convert.py

WORKDIR /app

ENTRYPOINT ["python", "/app/convert.py"]
