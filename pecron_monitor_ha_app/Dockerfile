ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24-2026.11.0
FROM ${BUILD_FROM}

ARG BUILD_VERSION=dev
ENV PECRON_APP_VERSION=${BUILD_VERSION}

LABEL io.hass.type="app"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Upstream library, pinned by commit. Installed from the archive tarball
# because the image has no git; --no-deps keeps requirements.txt the only
# source of dependency versions, and pip check fails the build if upstream
# gains a dependency we do not install.
ARG PECRON_MONITOR_VERSION=v0.8.4
ARG PECRON_MONITOR_SHA=438808b166b8cda023b4bd9ac9d7126ca5906583
RUN pip install --no-cache-dir --no-deps \
        "https://github.com/attractify-logan/pecron-monitor/archive/${PECRON_MONITOR_SHA}.tar.gz" \
    && pip check

COPY app /opt/pecron_app
ENV PYTHONPATH=/opt/pecron_app

COPY THIRD_PARTY_NOTICES.md /usr/share/doc/pecron-monitor-ha-app/THIRD_PARTY_NOTICES.md
