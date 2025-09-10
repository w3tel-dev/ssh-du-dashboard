FROM python:3.12-slim

# Install OpenSSH client and basic tools
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client bash coreutils findutils &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/ /app/
RUN pip install --no-cache-dir -r requirements.txt

ENV FLASK_ENV=production
ENV PORT=9090

EXPOSE 9090
CMD ["python", "main.py"]
