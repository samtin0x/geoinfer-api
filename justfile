# Development commands for GeoInfer

# Show available commands
default:
    @just --list

# Install dependencies including dev dependencies
install:
    uv sync --extra dev

# Setup pre-commit hooks
setup-pre-commit:
    uv run pre-commit install

# Format code with Black and fix auto-fixable linting issues with Ruff
format:
    @echo "Formatting with Black..."
    uv run black .
    @echo "Fixing auto-fixable issues with Ruff..."
    -uv run ruff check --fix .
    @echo "✅ Formatting complete! Some linting issues may require manual fixes."

# Type check with mypy (excluding problematic files)
typecheck:
    uv run mypy src/

# Clean up cache files
clean:
    rm -rf .ruff_cache/
    rm -rf .mypy_cache/
    rm -rf __pycache__/
    find . -name "*.pyc" -delete
    find . -name "*.pyo" -delete

# Database migration commands
db-upgrade:
    @echo "Running database migrations..."
    PYTHONPATH=. uv run alembic -c src/database/alembic.ini upgrade head

db-downgrade REVISION="base":
    @echo "Downgrading database to {{ REVISION }}..."
    PYTHONPATH=. uv run alembic -c src/database/alembic.ini downgrade {{ REVISION }}

db-migration MESSAGE:
    @echo "Creating new migration: {{ MESSAGE }}"
    PYTHONPATH=. uv run alembic -c src/database/alembic.ini revision --autogenerate -m "{{ MESSAGE }}"

db-history:
    @echo "Migration history:"
    PYTHONPATH=. uv run alembic -c src/database/alembic.ini history --verbose

db-current:
    @echo "Current database revision:"
    PYTHONPATH=. uv run alembic -c src/database/alembic.ini current

# Run tests with pytest (optional path parameter)
test PATH="tests/":
    PYTHONPATH=. uv run pytest {{ PATH }} -v

# Development server commands
dev:
    @echo "Starting GeoInfer API development server..."
    uv run python -c "from src.main import run_dev_server; run_dev_server()"

prod:
    @echo "Starting GeoInfer API production server..."
    uv run python -c "from src.main import run_prod_server; run_prod_server()"

# Docker development commands
docker-build:
    @echo "Building Docker development image..."
    docker-compose build

docker-up:
    @echo "Starting Docker development environment..."
    docker-compose up -d

docker-down:
    @echo "Stopping Docker development environment..."
    docker-compose down

