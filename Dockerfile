FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    libmagic-dev \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy all project files into container
COPY . /app

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expose Flask port
EXPOSE 5000

# Start the Flask app
CMD ["python", "app.py"]
