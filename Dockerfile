FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV DEMO_HOST=0.0.0.0
ENV DEMO_PORT=8080
EXPOSE 8080
CMD ["python3", "demo/server.py"]
