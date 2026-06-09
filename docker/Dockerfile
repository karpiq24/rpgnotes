FROM rocm/dev-ubuntu-24.04:7.2.2-complete

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ffmpeg curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CTranslate2 v4.7.1 ROCm wheel (cp312 = Ubuntu 24.04's default Python).
# The release zip extracts into a temp-linux/ subdir; filenames are manylinux_*, not linux_x86_64.
RUN set -eux \
    && curl -fL -o /tmp/ct2.zip \
        https://github.com/OpenNMT/CTranslate2/releases/download/v4.7.1/rocm-python-wheels-Linux.zip \
    && unzip /tmp/ct2.zip -d /tmp/ct2 \
    && WHEEL="$(find /tmp/ct2 -maxdepth 3 -name 'ctranslate2-*-cp312-cp312-*x86_64*.whl' | head -n1)" \
    && test -n "$WHEEL" \
    && pip install --break-system-packages --no-cache-dir "$WHEEL" \
    && rm -rf /tmp/ct2 /tmp/ct2.zip

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --break-system-packages --no-cache-dir ".[dev]"

COPY prompts/ ./prompts/
COPY template.md discord_speaker_mapping.json ./
COPY tests/ ./tests/

# Self-configuring entrypoint detects the host user + GPU device GIDs at
# startup and drops privileges (see docker/entrypoint.sh).
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
