FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV TRADEFOUNDRY_DATABASE_URL=postgresql+psycopg://tradefoundry:tradefoundry@db:5432/tradefoundry
ENV TRADEFOUNDRY_ARTIFACT_ROOT=/data/artifacts

CMD ["uvicorn", "tradefoundry.api:app", "--host", "0.0.0.0", "--port", "8000"]

