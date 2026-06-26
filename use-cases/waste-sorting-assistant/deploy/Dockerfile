FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py config.yaml lambda.py tool.py ./

CMD ["lambda.handler"]
