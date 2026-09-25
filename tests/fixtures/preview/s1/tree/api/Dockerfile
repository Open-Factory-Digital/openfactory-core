ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim
WORKDIR /app
COPY . .
# The compose file's healthcheck calls curl, which the slim image does not ship: a stand-in.
RUN install -m 0755 /app/curl /usr/local/bin/curl
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
