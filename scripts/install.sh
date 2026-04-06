#!/bin/bash
set -euo pipefail

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu" ]]; then
  echo "Warning: This script is designed to run on Linux only."
  exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
  read -p "Docker is not installed. Would you like to install it? (yes/no) " install_docker
  if [[ "$install_docker" == "yes" ]]; then
    echo "Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    echo "Adding Docker GPG key..."
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "Adding Docker repository..."
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    echo "Docker installed successfully!"
  else
    echo "Skipping Docker installation."
    exit 1
  fi
fi

# Check if user is in docker group
if ! groups $USER | grep &>/dev/null 'docker'; then
  echo "You are not in the Docker group. You will need to run the following command to add your user to the Docker group:"
  echo "sudo usermod -aG docker $USER"
  echo "Please log out and log back in for the changes to take effect."
fi

# Create necessary directories
echo "Creating directories..."
sudo mkdir -p /data/sites /data/certs/ca /data/sftp /data/proxy/conf.d
sudo chown -R $USER /data

# Manage .env file
if [[ ! -f .env ]]; then
  echo "Copying .env.example to .env"
  cp .env.example .env
  read -p "Would you like to auto-generate strong values for DB_PASSWORD, SITE_DB_PASSWORD, ADMIN_SECRET_KEY? (yes/no) " generate_secrets
  if [[ "$generate_secrets" == "yes" ]]; then
    echo "Generating secrets..."
    echo "DB_PASSWORD=$(openssl rand -hex 16)" >> .env
    echo "SITE_DB_PASSWORD=$(openssl rand -hex 16)" >> .env
    echo "ADMIN_SECRET_KEY=$(openssl rand -hex 16)" >> .env
    echo "Secrets generated and added to .env!"
  fi
fi

# Run docker-compose
echo "Running docker-compose up..."
docker-compose up -d --build

# Healthcheck instructions
echo "To check if everything is running, use: docker-compose ps"