FROM ubuntu:22.04

LABEL org.opencontainers.image.title="HOME AI Core DVR"
LABEL org.opencontainers.image.source="https://github.com/DeadSoulf/home-ai-core_dvr"
LABEL org.opencontainers.image.version="1.1.2"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        ffmpeg \
        libuuid1 \
        libstdc++6 \
        libgcc-s1 \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

ENV HCNETSDK_PATH=/opt/hikvision/lib
ENV LD_LIBRARY_PATH=/opt/hikvision/lib:/opt/hikvision/lib/HCNetSDKCom
ENV NVR_DATA_ROOT=/data
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOME=/tmp
ENV TMPDIR=/tmp

COPY sdk/lib/ /opt/hikvision/lib/
COPY bin/ /usr/local/bin/
COPY web/ /app/web/
COPY nvr/ /app/nvr/
COPY scripts/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh /usr/local/bin/sdk-* \
    && mkdir -p /data

WORKDIR /data
EXPOSE 8090
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/nvr/status', timeout=5).read()" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "/app/web/server.py"]
