FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OUTREACH_DATA_DIR=/data HOME=/tmp
WORKDIR /app
RUN groupadd --gid 10001 outreach && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin outreach && mkdir /data && chown outreach:outreach /data
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY outreach ./outreach
COPY resources ./resources
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "outreach.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
