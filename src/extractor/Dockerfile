# Build context is the repo root (see docker-compose.yml) so the image preserves the
# same src/extractor/ depth as the checkout — main.py resolves its repo root via
# Path(__file__).resolve().parents[2], which requires that depth to stay intact.
FROM python:3.12-slim

WORKDIR /app/src/extractor

COPY src/extractor/pyproject.toml ./
COPY src/extractor/*.py ./

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]