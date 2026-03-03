FROM python:3.13-slim

RUN pip install --no-cache-dir embedding-atlas

WORKDIR /data
EXPOSE 5055

ENTRYPOINT ["embedding-atlas", "--host", "0.0.0.0", "--port", "5055", "--no-auto-port"]
