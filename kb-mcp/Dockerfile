FROM python:3.12-slim
RUN pip install --no-cache-dir starlette==0.* uvicorn==0.*
WORKDIR /app
COPY server.py .
EXPOSE 8787
CMD ["python", "server.py"]
