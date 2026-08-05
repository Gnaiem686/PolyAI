FROM python:3.12-slim-trixie

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from langchain_mcp_adapters.client import MultiServerMCPClient"

COPY . .

EXPOSE 8000

CMD ["python", "app.py"]
