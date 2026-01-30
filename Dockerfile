# 1. Use an official lightweight Python image
FROM python:3.10-slim

# 2. Set the working directory container
WORKDIR /code

# 3. Copy requirements and install dependencies
# We do this first to leverage Docker caching
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# 4. Copy the application code
COPY ./app /code/app

# 5. Expose the port Cloud Run expects (8080 is default)
ENV PORT=8080

# 6. Run the application
# Note: Host must be 0.0.0.0 to listen outside the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]