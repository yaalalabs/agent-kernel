#!/bin/bash
#
# Sets up a local development environment for Agent Kernel.
#
# Installs pyenv, tfenv, nvm, uv, git and make if they're missing, sets
# Python to 3.12 and Terraform/Node to their latest versions, then syncs
# the ak-py project so `make lint*` and `pytest` work out of the box.
#
# Usage: ./scripts/dev-setup.sh

set -e

CUR_SCRIPT=$(readlink -f "${BASH_SOURCE[0]}")
REPO_ROOT=$(dirname "$(dirname "$CUR_SCRIPT")")

PYTHON_VERSION="3.12"
NVM_VERSION="v0.40.1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error()   { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ $1${NC}"; }
print_header()  { echo -e "\n${BLUE}=== $1 ===${NC}"; }

OS="$(uname -s)"

print_header "Checking git and make"
for cmd in git make; do
    if command -v "$cmd" &> /dev/null; then
        print_success "$cmd found"
    else
        print_error "$cmd not found. Please install $cmd before continuing."
        exit 1
    fi
done

print_header "Checking pyenv"
if command -v pyenv &> /dev/null; then
    print_success "pyenv found"
else
    print_warning "pyenv not found."
    if [ "$OS" == "Darwin" ]; then
        if ! command -v brew &> /dev/null; then
            print_error "Homebrew not found. Install it from https://brew.sh, then re-run this script."
            exit 1
        fi
        print_info "Installing pyenv via Homebrew..."
        brew install pyenv
    elif [ "$OS" == "Linux" ]; then
        print_info "Installing pyenv via https://pyenv.run..."
        curl -fsSL https://pyenv.run | bash
        export PATH="$HOME/.pyenv/bin:$PATH"
    else
        print_error "Unsupported OS: $OS. Install pyenv manually: https://github.com/pyenv/pyenv#installation"
        exit 1
    fi
    print_success "pyenv installed"
    print_warning "Add pyenv to your shell profile (see https://github.com/pyenv/pyenv#set-up-your-shell-environment-for-pyenv) then restart your shell."
fi
eval "$(pyenv init - 2>/dev/null)" || true

print_header "Setting Python to $PYTHON_VERSION"
if pyenv versions --bare 2>/dev/null | grep -q "^${PYTHON_VERSION}"; then
    print_success "Python $PYTHON_VERSION already installed via pyenv"
else
    print_info "Installing latest Python $PYTHON_VERSION.x via pyenv..."
    pyenv install --skip-existing "$PYTHON_VERSION"
    print_success "Python $PYTHON_VERSION installed"
fi
pyenv global "$PYTHON_VERSION"
print_success "pyenv global set to $PYTHON_VERSION"

print_header "Checking tfenv"
if command -v tfenv &> /dev/null; then
    print_success "tfenv found"
else
    print_warning "tfenv not found."
    if [ "$OS" == "Darwin" ]; then
        if ! command -v brew &> /dev/null; then
            print_error "Homebrew not found. Install it from https://brew.sh, then re-run this script."
            exit 1
        fi
        print_info "Installing tfenv via Homebrew..."
        brew install tfenv
        # brew link can fail to symlink tfenv's shims into PATH when a
        # plain `terraform` formula is already installed, so prepend
        # tfenv's own bin dir directly rather than relying on the link.
        export PATH="$(brew --prefix tfenv)/bin:$PATH"
        if brew list --formula terraform &> /dev/null; then
            print_warning "A plain 'terraform' Homebrew formula is installed and shadows tfenv."
            print_info "Run 'brew unlink terraform && brew link tfenv' to use tfenv in new shells."
        fi
    elif [ "$OS" == "Linux" ]; then
        print_info "Installing tfenv via git clone..."
        git clone --depth=1 https://github.com/tfenv/tfenv.git "$HOME/.tfenv"
        export PATH="$HOME/.tfenv/bin:$PATH"
        print_warning "Add \$HOME/.tfenv/bin to your PATH in your shell profile, then restart your shell."
    else
        print_error "Unsupported OS: $OS. Install tfenv manually: https://github.com/tfenv/tfenv#installation"
        exit 1
    fi
    print_success "tfenv installed"
fi

print_header "Setting Terraform to latest"
tfenv install latest
tfenv use latest
print_success "Terraform set to latest ($(tfenv version-name))"

print_header "Checking nvm"
if [ -z "$NVM_DIR" ]; then
    export NVM_DIR="$HOME/.nvm"
fi
if [ -s "$NVM_DIR/nvm.sh" ]; then
    print_success "nvm found"
else
    print_info "Installing nvm $NVM_VERSION..."
    curl -o- "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" | bash
    print_success "nvm installed"
fi
# shellcheck disable=SC1091
\. "$NVM_DIR/nvm.sh"

print_header "Setting Node to latest"
nvm install node
nvm use node
nvm alias default node
print_success "Node set to latest ($(node --version))"

print_header "Checking uv"
if command -v uv &> /dev/null; then
    print_success "uv found ($(uv --version))"
else
    print_info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    print_success "uv installed"
fi

print_header "Setting up ak-py"
cd "$REPO_ROOT/ak-py"
./build.sh
print_success "ak-py virtual environment ready (ak-py/.venv)"

print_header "Setup complete"
print_info "Activate the venv with: source ak-py/.venv/bin/activate"
print_info "Run tests with:         cd ak-py && uv run pytest"
print_info "Run lint checks with:   make lint-check-all"
