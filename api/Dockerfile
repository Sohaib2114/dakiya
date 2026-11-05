# build stage: install dependencies into a venv
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS build
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# runtime stage: only python, the venv and the code
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
# CVE-2026-109518: python:3.12-slim still ships apt 3.0.3, remove this line once the base image has the fix
RUN apt-get update && apt-get install -y --only-upgrade apt libapt-pkg7.0 && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --no-create-home app
COPY --from=build /venv /venv
WORKDIR /app
COPY --chmod=755 app ./app
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
