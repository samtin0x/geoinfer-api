# GeoInfer API - Local Development

AI-powered GPS coordinate prediction from images using GeoCLIP models.

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- `uv` package manager

### Local Development Setup

1. **Clone and setup**
   ```bash
   git clone <repository-url>
   cd geoinfer-api
   just install
   ```

2. **Environment configuration**
   ```bash
   cp env.example .env
   # Edit .env with your local settings
   ```

3. **Start infrastructure services**
   ```bash
   just docker-up
   ```
   This starts PostgreSQL and Redis in Docker containers.

4. **Initialize database**
   ```bash
   just db-upgrade
   just seed-roles
   ```

5. **Run the API locally**
   ```bash
   just dev
   ```
   The API runs on your host machine with hot reloads at `http://localhost:8010`

## 🛠️ Development Commands

```bash
# Infrastructure
just docker-up          # Start PostgreSQL + Redis containers
just docker-down        # Stop containers

# API Development
just dev                 # Run API locally with hot reload
just prod               # Run API in production mode

# Database
just db-upgrade         # Run migrations
just db-migration "msg" # Create new migration
just seed-roles        # Initialize system roles

# Code Quality
just format             # Format code (Black + Ruff)
just typecheck         # Type checking (mypy)
just test              # Run tests (pytest)
```

## 🐳 Local vs Production

- **Local Development**: Database/Redis in Docker, API on host with `--reload`
- **Production**: Single `Dockerfile` with all services containerized

## 📚 API Documentation

- **Interactive docs**: `http://localhost:8010/docs`
- **Health check**: `http://localhost:8010/health`

## 🔑 Key Environment Variables

```bash
# Database (for local Docker containers)
DATABASE_URL="postgresql://geoinfer:geoinfer_dev_password@localhost:5432/geoinfer"

# Redis (for local Docker container)
REDIS_URL="redis://localhost:6379/0"

# External services (add your keys)
SUPABASE_URL="your-supabase-url"
SUPABASE_KEY="your-supabase-anon-key"
SUPABASE_JWT_SECRET="your-jwt-secret"
RESEND_API_KEY="your-resend-api-key"
STRIPE_SECRET_KEY="your-stripe-secret-key"
```

That's it! You're ready to develop locally with fast hot reloads. 🎉