# A Dockerfile for a preview of `shop`, drafted by `openfactory preview propose` (ADR-0050).
# Nothing was built or run: `--prove` builds it once, from the base branch, on the deployment's
# own daemon — never on a laptop. Each line says where it was read.
# inferred · .python-version:1
FROM python:3.12-slim
WORKDIR /app
# The repository's own files and directories — never `COPY . .` — and shop.Dockerfile.dockerignore
# keeps `.git` and every `.env` out of them too.
COPY manage.py requirements.txt ./
COPY shop ./shop
# observed · .openfactory/project.yaml:3 — the manifest's `setup:`
RUN pip install -r requirements.txt
# inferred · manage.py
EXPOSE 8000
# inferred · manage.py
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
