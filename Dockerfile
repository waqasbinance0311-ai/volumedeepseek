FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files
COPY . .

# Change to correct working directory if needed
WORKDIR /app

CMD ["python", "final_bot.py"]
