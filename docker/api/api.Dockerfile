FROM python:3.11.11-slim

RUN mkdir -p /usr/src/app/
WORKDIR /usr/src/app/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    pkg-config \
    libpq-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf2.0-dev \
    libfreetype6-dev \
    libffi-dev \
    meson \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install poetry

COPY poetry.lock pyproject.toml /usr/src/app/

RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root

COPY . /usr/src/app/

EXPOSE 8000

# Run migrations then start API with multiple workers
CMD ["sh", "-c", "poetry run alembic upgrade head && poetry run uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level info"]
