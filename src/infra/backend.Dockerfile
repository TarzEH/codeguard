FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code edits do not invalidate the pip layer.
# Installing from requirements.txt (not a loose `pip install flask requests`)
# is what makes this image reproducible.
COPY src/backEnd/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY src/backEnd/ ./

RUN useradd --system --uid 10001 --no-create-home codeguard \
    && chown -R codeguard:codeguard /app
USER codeguard

EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4).status==200 else 1)"

# One worker process per container keeps exactly one participant per replica in
# the leader election; threads handle the I/O-bound concurrency.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "1", "--threads", "8", "--worker-class", "gthread", \
     "--timeout", "120", "--graceful-timeout", "30", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "wsgi:app"]
