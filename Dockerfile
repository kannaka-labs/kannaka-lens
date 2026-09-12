# One execution target (ADR-0001 §3). The image carries ffmpeg so that no host
# needs it installed -- debain2, the primary node, does not have it and is not
# going to get it just for this.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/lens
COPY pyproject.toml README.md LICENSE NOTICE run-tests.sh ./
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts
RUN pip install --no-cache-dir .

# Fonts, keys and scratch paths are injected, never baked in.
ENV LENS_WORK=/work
VOLUME ["/work"]
WORKDIR /work
ENTRYPOINT ["lens"]
CMD ["--help"]
