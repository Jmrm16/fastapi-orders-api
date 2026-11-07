.PHONY: help install run dev test test-cov migrate seed clean

help:
	@echo "Available commands:"
	@echo "  make install    - Install dependencies in virtual environment"
	@echo "  make dev        - Run development server with auto-reload"
	@echo "  make test       - Execute automated test suite with pytest"
	@echo "  make test-cov   - Run test suite with coverage report"
	@echo "  make migrate    - Apply database migrations with Alembic"
	@echo "  make seed       - Seed initial demo products and users"
	@echo "  make clean      - Clean cache and temporary build artifacts"

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -v

test-cov:
	pytest -v --cov=app --cov-report=term-missing

migrate:
	alembic upgrade head

seed:
	python scripts/seed_db.py

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
