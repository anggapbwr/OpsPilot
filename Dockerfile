FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ANSIBLE_CONFIG=/app/ansible/ansible.cfg

WORKDIR /app

# Install system dependencies: curl for health checks, docker CLI for container operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir ansible-core

# Copy Ansible requirements and install community collections
COPY ansible/requirements.yml ./ansible/
RUN ansible-galaxy collection install -r ./ansible/requirements.yml

# Copy application code, policies, and automation assets
COPY app ./app
COPY ansible ./ansible
COPY policies ./policies
COPY logs ./logs

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
