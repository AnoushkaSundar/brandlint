# BrandLint API image. Build context is the repo ROOT (see docker-compose.yml:
#   build: { context: ., dockerfile: api/Dockerfile }
# so that requirements/ (at the repo root) is available to install.
FROM python:3.11-slim

WORKDIR /app

# System deps: Tesseract for OCR parsing (block 3), libs for PyMuPDF/Pillow.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements/base.txt

# App code (api/ contents land at /app, so `app` package is /app/app).
COPY api/ /app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
