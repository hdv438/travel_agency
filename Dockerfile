# Production Dockerfile for agency_tracking (Frappe v15) on Railway
#
# Single-container architecture running:
# - Gunicorn WSGI server (web API)
# - Background RQ worker (async jobs)
# - Frappe Scheduler (watchdogs & cron tasks)
# - Redis Server (caching & queues)
# All orchestrated via Supervisord.
#
# MariaDB is external -- provisioned via Railway MySQL/MariaDB plugin.

FROM python:3.11-slim-bookworm AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    BENCH_PATH=/home/frappe/bench

# System packages & native dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl wget gnupg build-essential pkg-config \
        python3-dev python3-venv default-libmysqlclient-dev \
        libmariadb-dev libmariadb-dev-compat \
        libssl-dev libffi-dev libjpeg62-turbo-dev zlib1g-dev libwebp-dev \
        mariadb-client redis-server \
        wkhtmltopdf xfonts-75dpi xfonts-base \
        tesseract-ocr \
        supervisor cron \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g yarn \
    && pip install --no-cache-dir frappe-bench \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user
RUN useradd -ms /bin/bash frappe
USER frappe
WORKDIR /home/frappe

# Git identity configuration for bench initialization
RUN git config --global user.email "deploy@railway.app" \
    && git config --global user.name "Railway Deploy"

# Initialize Frappe v15 Bench framework
RUN bench init --skip-redis-config-generation --frappe-branch version-15 ${BENCH_PATH}

WORKDIR ${BENCH_PATH}

# Copy agency_tracking app source code into bench
COPY --chown=frappe:frappe . apps/agency_tracking

# Install python dependencies from pyproject.toml and register app
RUN ./env/bin/pip install --no-cache-dir -e apps/agency_tracking \
    && printf '\n%s\n' agency_tracking >> sites/apps.txt

# Compile Frappe Desk static assets
RUN bench build --app frappe

# Save initial sites/ directory as backup template for volume mounting
RUN cp -a sites /home/frappe/sites-init

# Runtime setup
USER root
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/log/supervisor \
    && chown -R frappe:frappe /var/log/supervisor /entrypoint.sh

EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

