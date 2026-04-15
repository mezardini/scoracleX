# Stage 1: Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies for psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime library for Postgres
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies from builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy the rest of your application code
COPY . .

# 1. Collect static files
# Note: Ensure all required env vars for Django are available or handled in settings
RUN python manage.py collectstatic --noinput

# 2. Create the user
RUN useradd -m appuser

# 3. Copy and prepare the entrypoint script
COPY entrypoint.sh /entrypoint.sh

# 4. Fix permissions
USER root
RUN chmod +x /entrypoint.sh

# 5. Switch to the non-privileged user
USER appuser

EXPOSE 8000

# 6. Launch via the script
ENTRYPOINT ["/entrypoint.sh"]