FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx \
        supervisor \
        apache2-utils \
        cron \
        curl \
        git \
        vim \
    && rm -rf /var/lib/apt/lists/*

COPY docker/crontab /etc/cron.d/kinsync
RUN chmod 0644 /etc/cron.d/kinsync

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY app.py .
COPY templates/ templates/

COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/nginx.conf /etc/nginx/sites-available/default
COPY docker/radicale.conf /etc/radicale/config
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data"]
EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
