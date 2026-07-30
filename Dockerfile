# Use Python 3.12 slim to match your dependency builds
FROM python:3.12-slim

# Prevent Python from writing .pyc files and force unbuffered logging so errors show up in Render immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install minimal OS build tools required for C-extension packages (like cryptography/cffi)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to take advantage of Docker build caching
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all remaining bot source code into the container
COPY . .

# Expose Render's default Web Service port
EXPOSE 10000

# Start command
CMD ["python", "run.py"]
