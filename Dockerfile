FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-lock.linux.generated.txt /app/requirements-lock.txt

RUN python -m pip install --no-cache-dir -r /app/requirements-lock.txt

COPY app/ /app/app/

RUN useradd --system --uid 10001 --create-home appuser

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

