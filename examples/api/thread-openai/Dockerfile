FROM python:3.12-slim

WORKDIR /app
COPY dist/ /app/

EXPOSE 8000

CMD ["python", "-c", "from app import runner; runner()"]