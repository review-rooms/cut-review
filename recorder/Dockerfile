# cut-review local recorder. Build from the repo root:
#   docker build -f recorder/Dockerfile -t cut-review-recorder .
# Run from a room project (see recorder/README.md for the full command).
FROM python:3.12-slim
WORKDIR /app
COPY src/cut_review /app/src/cut_review
COPY recorder/server.py recorder/page.html /app/recorder/
ENV ROOM=/room PORT=8790 HOST=0.0.0.0 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8790
CMD ["python3", "/app/recorder/server.py"]
