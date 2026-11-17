FROM python:3.12-slim

WORKDIR /app
COPY data/ /app/

EXPOSE 8000

# The edge. The agent runner app overrides this with the module's agent_runner_command.
CMD ["python", "app_io_handler.py"]
