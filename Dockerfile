# ... (all the Stage 1 and Stage 2 code you already have)

# 1. Collect static files
RUN python manage.py collectstatic --noinput

# 2. Create the user
RUN useradd -m appuser

# 3. Copy the entrypoint script from your local machine to the container
COPY entrypoint.sh /entrypoint.sh

# 4. Fix permissions so the script can run
USER root
RUN chmod +x /entrypoint.sh

# 5. Switch back to the non-privileged user
USER appuser

EXPOSE 8000

# 6. Launch via the script
ENTRYPOINT ["/entrypoint.sh"]