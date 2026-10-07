FROM ubuntu:22.04

LABEL org.opencontainers.image.title="h.a.c._nvr"
LABEL org.opencontainers.image.version="1.0.0"

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

COPY sdk/lib/ /opt/hikvision/lib/
COPY bin/ /usr/local/bin/
COPY web/ /app/web/
COPY nvr/ /app/nvr/
COPY scripts/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh /usr/local/bin/sdk-* \
    && mkdir -p /app/output/hls /app/output/archive /app/output/recordings /app/output/logs /app/sdkLog

WORKDIR /app
EXPOSE 8090
VOLUME ["/app/output"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD /usr/local/bin/sdk-smoke >/tmp/hcnetsdk-health.log 2>&1 || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "/app/web/server.py"]
