#!/bin/sh
# Start script for the request-handler Lambda (handler_path = "run.sh"). The Lambda Web Adapter layer
# runs it through AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap, then forwards requests to the app on AWS_LWA_PORT.
cd /var/task
export PYTHONPATH="/var/task:${PYTHONPATH}"
exec python3 app_stream_server.py
