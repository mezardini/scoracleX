# Stage 1: Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a specific folder (/install)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime library for Postgres
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy the rest of your application code
COPY . .


# 2. Create the user
RUN useradd -m appuser

# 3. Copy and prepare the entrypoint script
COPY entrypoint.sh /entrypoint.sh

# 4. Fix permissions for the script AND the app directory
USER root
RUN chmod +x /entrypoint.sh && chown -R appuser:appuser /app

# 5. Switch to the non-privileged user
USER appuser

EXPOSE 8000

# 6. Launch via the script
ENTRYPOINT ["/entrypoint.sh"]