FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY handler.py transform.py db.py ./

CMD ["handler.handler"]