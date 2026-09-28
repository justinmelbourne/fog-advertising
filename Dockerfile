FROM python:3.11-slim

# Install FFmpeg and FFprobe (required for audio extraction and clipping)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash fogapp
WORKDIR /app

# Copy and install Python dependencies first (layer cache efficiency)
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-cloud.txt

# Copy application code
COPY engine/ ./engine/
COPY cloud_service/ ./cloud_service/

# Change ownership
RUN chown -R fogapp:fogapp /app
USER fogapp

# Cloud Run injects PORT env var; default to 8080
ENV PORT=8080
EXPOSE 8080

# Use gunicorn for production WSGI serving
CMD exec gunicorn --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile - \
    cloud_service.main:app
