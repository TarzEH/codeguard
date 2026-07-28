# 3.0 is needed for the `http-check send` syntax used to probe /health.
FROM haproxy:3.0-alpine

COPY haproxy.cfg /usr/local/etc/haproxy/haproxy.cfg

EXPOSE 80 8404
