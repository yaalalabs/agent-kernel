FROM python:3.12-slim

WORKDIR /app
COPY data/ /app/

EXPOSE 8000

CMD ["python", "-c", "from app import main; main()"]
