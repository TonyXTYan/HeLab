FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 xvfb x11-utils libopengl0 \
    libgl1 libglib2.0-0 libfontconfig1 libdbus-1-3 libxkbcommon0 libxkbcommon-x11-0 \
    libnss3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxi6 libasound2t64 libxshmfence1 libgbm1 \
    libxkbfile1 libxcb-cursor0 libgssapi-krb5-2 libsnappy1v5 libminizip1t64 libwebp7 libwebpdemux2 libwebpmux3 libopus0 liblcms2-2 libxfixes3 libcups2t64 libpulse0 libwayland-cursor0 libwayland-egl1 \
    curl ca-certificates git procps && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH=/root/.local/bin:$PATH
RUN uv python install 3.13 && uv venv --seed --python 3.13 /venv
COPY requirements.lock /tmp/requirements.lock
RUN . /venv/bin/activate && uv pip install -r /tmp/requirements.lock
ENV QT_QPA_PLATFORM=offscreen
