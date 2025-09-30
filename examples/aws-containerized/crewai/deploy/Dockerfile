FROM python:3.12-slim

WORKDIR /app
COPY data/ /app/

RUN mkdir -p /tmp /var/tmp /tmp/crewai && \
    chmod 1777 /tmp /var/tmp /tmp/crewai

ENV TMPDIR=/tmp \
    TEMP=/tmp \
    TMP=/tmp

EXPOSE 8000

CMD ["python", "-c", "from app import runner; runner()"]