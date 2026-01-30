# Use the official lightweight Python image.
FROM python:3.11-slim

# Allow statements and errors to be immediately logged to the Cloud Run logs
ENV PYTHONUNBUFFERED True

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

# Install production dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Run the web service on container startup. 
# Cloud Run sets the PORT environment variable automatically.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port $PORT