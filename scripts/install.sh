#!/bin/bash

# Ensure openssl is installed
if ! command -v openssl &> /dev/null
then
    echo "openssl could not be found. Please install it to proceed."
    exit 1
fi

# Define variables for the secrets
DB_PASSWORD=$(openssl rand -hex 32)
SITE_DB_PASSWORD=$(openssl rand -hex 32)
ADMIN_SECRET_KEY=$(openssl rand -hex 64)

# Replace existing values in .env file
if [ -f .env ]; then
    sed -i.bak -e "s/^DB_PASSWORD=.*/DB_PASSWORD=$DB_PASSWORD/"
    sed -i.bak -e "s/^SITE_DB_PASSWORD=.*/SITE_DB_PASSWORD=$SITE_DB_PASSWORD/"
    sed -i.bak -e "s/^ADMIN_SECRET_KEY=.*/ADMIN_SECRET_KEY=$ADMIN_SECRET_KEY/"
else
    echo "Creating .env from .env.example"
    cp .env.example .env
    echo "DB_PASSWORD=$DB_PASSWORD" >> .env
    echo "SITE_DB_PASSWORD=$SITE_DB_PASSWORD" >> .env
    echo "ADMIN_SECRET_KEY=$ADMIN_SECRET_KEY" >> .env
fi

# Use docker compose instead of docker-compose
docker compose up -d