# 描画ツールチェーン（Node / LibreOffice / poppler / 日本語フォント）を固定するイメージ。
# 第三者コード（npm 依存・LibreOffice）はホストで直接実行せず、このコンテナ内で実行する。
FROM node:22-bookworm

# LibreOffice（PPTX→PDF）、poppler（PDF→PNG）、Noto CJK（日本語描画）、Python（検証・adapter）
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-impress \
      poppler-utils \
      fonts-noto-cjk \
      fontconfig \
      python3 \
      python3-venv \
      python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

# Python 依存は venv に隔離（Debian の externally-managed 制約を避けるため）
COPY requirements-dev.txt /opt/psl/requirements-dev.txt
RUN python3 -m venv /opt/psl/venv \
 && /opt/psl/venv/bin/pip install --no-cache-dir -r /opt/psl/requirements-dev.txt
ENV PATH=/opt/psl/venv/bin:$PATH

# Node 依存は上流の package-lock.json で固定し、submodule を汚さないようイメージ内に置く
COPY vendor/presentation-skill/package.json vendor/presentation-skill/package-lock.json /opt/psl/node/
RUN cd /opt/psl/node && npm ci --no-audit --no-fund --omit=dev
ENV PPTX_NODE_MODULES=/opt/psl/node/node_modules \
    NODE_PATH=/opt/psl/node/node_modules \
    HOME=/tmp

WORKDIR /repo
