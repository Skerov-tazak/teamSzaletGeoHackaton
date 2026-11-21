#!/bin/bash
# Field Under Pressure — Quick start script
# Starts the entire application: database, backend, frontend, and optionally the RAG index

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Field Under Pressure — Starting application${NC}"
echo ""

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

if ! command -v python &> /dev/null; then
    echo -e "${RED}❌ Python not found${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker not found${NC}"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python, Docker, Node.js found${NC}"
echo ""

# Check Python version
PYTHON_VERSION=$(python --version | cut -d' ' -f2)
echo -e "Using Python: $PYTHON_VERSION"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}📦 Creating Python virtual environment...${NC}"
    python -m venv .venv
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source .venv/bin/activate

# Install/update dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
pip install -q -r requirements.txt

# Check .env file
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}📋 Creating .env file from .env.example...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ .env created${NC}"
fi

# Start Docker services (Postgres + Qdrant)
echo -e "${BLUE}Starting Docker services (Postgres + Qdrant)...${NC}"
docker compose up -d

echo -e "${GREEN}✓ Docker services started${NC}"

# Wait for database to be ready
echo -e "${BLUE}Waiting for database to be ready...${NC}"
max_attempts=30
attempt=0
while ! docker compose exec -T db pg_isready -U fieldpressure -d fieldpressure > /dev/null 2>&1; do
    if [ $attempt -eq $max_attempts ]; then
        echo -e "${RED}❌ Database did not become ready in time${NC}"
        exit 1
    fi
    attempt=$((attempt + 1))
    echo -n "."
    sleep 1
done
echo -e "${GREEN} ready${NC}"
echo ""

# Run migrations
echo -e "${BLUE}Running database migrations...${NC}"
python manage.py migrate --quiet

# Create superuser if needed
echo -e "${BLUE}Ensuring superuser exists...${NC}"
python manage.py shell << EOF 2>/dev/null
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print('✓ Admin user created (username: admin, password: admin)')
else:
    print('✓ Admin user already exists')
EOF

# Set demo date if not already set
echo -e "${BLUE}Configuring demo date...${NC}"
python manage.py shell << EOF 2>/dev/null
from core.models import Clock
from datetime import datetime
if not Clock.objects.exists():
    Clock.objects.create(reference_date=datetime(2024, 5, 15).date())
    print('✓ Demo date set to 2024-05-15')
else:
    print('✓ Demo date already set')
EOF

# Seed development data
echo -e "${BLUE}Seeding development data...${NC}"
python manage.py assistant_dev_seed > /dev/null 2>&1 || true
echo -e "${GREEN}✓ Development data seeded${NC}"
echo ""

# Build frontend
echo -e "${BLUE}Building frontend...${NC}"
cd frontend
npm install -q
npm run build > /dev/null 2>&1
cd ..
echo -e "${GREEN}✓ Frontend built${NC}"
echo ""

# Optional: Build RAG index
echo -e "${YELLOW}RAG index setup:${NC}"
if [ ! -d "assistant/data" ] || [ -z "$(ls -A assistant/data 2>/dev/null)" ]; then
    echo -e "${BLUE}Building RAG index (this may take 2-4 minutes on first run)...${NC}"
    python manage.py rag_ingest --quiet > /dev/null 2>&1
    echo -e "${GREEN}✓ RAG index built${NC}"
else
    echo -e "${GREEN}✓ RAG index already exists${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Application ready!${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo ""
echo -e "Start the backend server:"
echo -e "  ${YELLOW}python manage.py runserver${NC}"
echo ""
echo -e "Or in a separate terminal, watch frontend changes:"
echo -e "  ${YELLOW}cd frontend && npm run watch${NC}"
echo ""
echo -e "Open in your browser:"
echo -e "  🌐 Dashboard:        ${BLUE}http://localhost:8000${NC}"
echo -e "  📚 API Docs:         ${BLUE}http://localhost:8000/api/docs/${NC}"
echo -e "  🔧 Django Admin:     ${BLUE}http://localhost:8000/admin/${NC}"
echo -e "                       (admin / admin)"
echo -e "  🧠 Qdrant Dashboard: ${BLUE}http://localhost:6333/dashboard${NC}"
echo ""
echo -e "Docker commands:"
echo -e "  ${YELLOW}docker compose stop${NC}      — Stop services (keep data)"
echo -e "  ${YELLOW}docker compose down -v${NC}   — Stop and wipe all data"
echo -e "  ${YELLOW}docker compose ps${NC}        — Check service status"
echo ""
