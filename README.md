## How to install
docker build -t pdftohtml-api .

## How to run
docker run -p 8000:8000 -v $(pwd):/app pdftohtml-api

## Healthcheck
curl --location 'http://127.0.0.1:8000/health'

## How to run
curl -X POST http://127.0.0.1:8000/extract-pdf \
  -F 'file=@yourfile.pdf'
