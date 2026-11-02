# CUDA 12.4 development tools are required by the configured CuPy/Triton backend.
# No global Torch installation: use only the protected persistent venv.
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \
    COMFY_DIR=/workspace/ComfyUI COMFY_PORT=8888 \
    COMFY_LOG_DIR=/workspace/wan-cloud-logs COMFY_START_TIMEOUT=300 \
    WAN_AUTOSTART=0
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates software-properties-common gnupg && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev python3 python3-venv python3-pip \
    git curl wget ffmpeg tmux build-essential pkg-config unzip \
    openssh-server openssh-client util-linux iproute2 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* && \
    mkdir -p /run/sshd && \
    printf '\nPasswordAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/wan.conf
WORKDIR /opt/wan-cloud-toolkit
COPY . /opt/wan-cloud-toolkit/
RUN python3.11 tools/check_python_headers.py && \
    python3.11 -m venv /tmp/wan-image-probe && \
    /tmp/wan-image-probe/bin/python -m pip --version && \
    rm -rf /tmp/wan-image-probe && \
    chmod +x docker/entrypoint.sh docker/autostart.sh fast-start.sh start.sh install/verify.sh
EXPOSE 22 8888
ENTRYPOINT ["/opt/wan-cloud-toolkit/docker/entrypoint.sh"]
