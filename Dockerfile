FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the application code into the image so the container is self-contained
# and does not depend on a host bind mount to find main.py.
COPY . .

CMD ["python", "main.py"]
