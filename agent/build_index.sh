#!/bin/bash
# Build the RAG index for Agent Kernel documentation and examples

set -e

echo "======================================================================"
echo "Building Agent Kernel RAG Index"
echo "======================================================================"

# Check if repository is cloned
echo ""
echo "Checking for agent-kernel repository clone..."
REPO_PATH="/tmp/agent-kernel-rag"
if [ ! -d "$REPO_PATH" ]; then
    echo "Repository not found at $REPO_PATH"
    echo "Cloning agent-kernel repository..."
    cd /tmp
    rm -rf agent-kernel-rag
    git clone --depth 1 git@github.com:yaalalabs/agent-kernel.git agent-kernel-rag
    echo "✓ Repository cloned successfully"
else
    echo "✓ Repository already cloned at $REPO_PATH"
    pushd $REPO_PATH
    git pull origin develop
    popd
fi

# Remove existing index if --rebuild flag is passed
if [ "$1" = "--rebuild" ] || [ "$1" = "-r" ]; then
    echo ""
    echo "Removing existing index..."
    rm -rf rag_storage/
    echo "✓ Existing index removed"
fi

# Check if index already exists
if [ -d "rag_storage" ] && [ -f "rag_storage/docstore.json" ]; then
    echo ""
    echo "Index already exists at ./rag_storage/"
    echo "Use '$0 --rebuild' to force rebuild"
    echo ""
    echo "======================================================================"
    exit 0
fi

# Build the index
echo ""
echo "Building RAG index..."
echo ""

uv run python -c "
from rag_system import get_rag_instance
import sys

try:
    print('Initializing RAG system...')
    rag = get_rag_instance(rebuild=True)
    print('\n✓ Index built successfully!')
    print(f'✓ Index persisted to ./rag_storage/')
except Exception as e:
    print(f'\n❌ Error building index: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo ""
    echo "======================================================================"
    echo "✓ RAG Index Built Successfully!"
    echo "======================================================================"
    echo ""
    echo "Index location: ./rag_storage/"
    echo ""
    echo "Next steps:"
    echo "  - Test the index: uv run python test_rag.py"
    echo "  - Run the agent: uv run python app.py"
    echo ""
    echo "To rebuild in the future:"
    echo "  $0 --rebuild"
    echo ""
    echo "======================================================================"
else
    echo ""
    echo "======================================================================"
    echo "❌ Index build failed"
    echo "======================================================================"
    exit 1
fi
