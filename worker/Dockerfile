# build stage: install dependencies into a venv
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# runtime stage: only python, the venv and the code
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
# CVE-2026-76844, CVE-2026-85091: python:3.12-slim still ships the old zlib1g, remove this line once the base image has the fix
RUN apt-get update && apt-get install -y --only-upgrade zlib1g && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --no-create-home app
COPY --from=build /venv /venv
WORKDIR /app
COPY --chmod=644 worker.py .
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001
CMD ["python", "worker.py"]
