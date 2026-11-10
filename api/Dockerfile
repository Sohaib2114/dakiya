# build stage: install dependencies into a venv
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS build
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# runtime stage: only python, the venv and the code
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
# CVE-2026-76844, CVE-2026-85091: python:3.12-slim still ships the old zlib1g, remove this line once the base image has the fix
RUN apt-get update && apt-get install -y --only-upgrade zlib1g && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --no-create-home app
COPY --from=build /venv /venv
WORKDIR /app
COPY --chmod=755 app ./app
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
