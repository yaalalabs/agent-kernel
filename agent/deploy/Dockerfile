FROM python:3.12-slim

WORKDIR /app
COPY data/ /app/

RUN mkdir -p /tmp /var/tmp && \
    chmod 1777 /tmp /var/tmp

ENV TMPDIR=/tmp \
    TEMP=/tmp \
    TMP=/tmp \
    HOME=/tmp

EXPOSE 8000

CMD ["python", "-c", "from app import main; main()"]
