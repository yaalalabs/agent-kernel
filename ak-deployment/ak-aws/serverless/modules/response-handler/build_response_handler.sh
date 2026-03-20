#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default values
MAIN_PACKAGE_PATH=""
OUTPUT_DIR="${SCRIPT_DIR}/response_handler_dist"
OUTPUT_ZIP="${SCRIPT_DIR}/response_handler_dist.zip"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --package-path)
            MAIN_PACKAGE_PATH="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --output-zip)
            OUTPUT_ZIP="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 --package-path <path_to_main_package_folder> [--output-dir <output_directory>] [--output-zip <output_zip_file>]"
            echo ""
            echo "Options:"
            echo "  --package-path    Path to the main Lambda package folder (e.g., dist/) that contains data/ subfolder (required)"
            echo "  --output-dir      Output directory for the response handler package (default: ./response_handler_dist)"
            echo "  --output-zip      Output zip file path (default: ./response_handler_dist.zip)"
            echo "  -h, --help        Show this help message"
            echo ""
            echo "Example:"
            echo "  $0 --package-path /path/to/examples/aws-serverless/openai/dist"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$MAIN_PACKAGE_PATH" ]; then
    print_error "Missing required argument: --package-path"
    echo "Use -h or --help for usage information"
    exit 1
fi

# Resolve to absolute path
MAIN_PACKAGE_PATH="$(cd "$MAIN_PACKAGE_PATH" 2>/dev/null && pwd || echo "$MAIN_PACKAGE_PATH")"

print_info "Starting response handler package build..."
print_info "Main package path: $MAIN_PACKAGE_PATH"
print_info "Output directory: $OUTPUT_DIR"
print_info "Output zip file: $OUTPUT_ZIP"

# Step 1: Clean up existing output
print_info "Step 1: Cleaning up existing output..."
rm -rf "$OUTPUT_DIR"
rm -f "$OUTPUT_ZIP"
mkdir -p "$OUTPUT_DIR"

# Step 2: Extract agentkernel from main package
print_info "Step 2: Extracting agentkernel from main package..."

if [ ! -d "$MAIN_PACKAGE_PATH" ]; then
    print_error "Main package directory not found at: $MAIN_PACKAGE_PATH"
    exit 1
fi

# Check if data folder exists
DATA_DIR="$MAIN_PACKAGE_PATH/data"
if [ ! -d "$DATA_DIR" ]; then
    print_error "data folder not found at: $DATA_DIR"
    print_info "Contents of package directory:"
    ls -la "$MAIN_PACKAGE_PATH"
    exit 1
fi

# Check if agentkernel exists in the data folder
if [ ! -d "$DATA_DIR/agentkernel" ]; then
    print_error "agentkernel folder not found in $DATA_DIR"
    print_info "Contents of data directory:"
    ls -la "$DATA_DIR"
    exit 1
fi

# Copy agentkernel to output directory
print_info "Copying agentkernel from $DATA_DIR to output directory..."
cp -r "$DATA_DIR/agentkernel" "$OUTPUT_DIR/"

# Step 3: Install minimal dependencies
print_info "Step 3: Installing minimal dependencies (pydantic, boto3)..."

# Check if uv is available
if command -v uv >/dev/null 2>&1; then
    print_info "Using uv to install dependencies..."
    uv pip install --target="$OUTPUT_DIR" --no-deps pydantic boto3
else
    print_warning "uv not found, falling back to pip..."
    if command -v pip3 >/dev/null 2>&1; then
        pip3 install --target="$OUTPUT_DIR" --no-deps pydantic boto3
    elif command -v pip >/dev/null 2>&1; then
        pip install --target="$OUTPUT_DIR" --no-deps pydantic boto3
    else
        print_error "Neither uv nor pip found. Please install one of them."
        exit 1
    fi
fi

# Step 4: Copy response_handler.py to root
print_info "Step 4: Copying response_handler.py to root of package..."

RESPONSE_HANDLER_SOURCE="$OUTPUT_DIR/agentkernel/deployment/aws/serverless/internal/response_handler.py"

if [ ! -f "$RESPONSE_HANDLER_SOURCE" ]; then
    print_error "response_handler.py not found at expected location: $RESPONSE_HANDLER_SOURCE"
    print_info "Searching for response_handler.py..."
    find "$OUTPUT_DIR" -name "response_handler.py" -type f
    exit 1
fi

cp "$RESPONSE_HANDLER_SOURCE" "$OUTPUT_DIR/response_handler.py"
print_info "Copied response_handler.py to $OUTPUT_DIR/response_handler.py"

# Step 5: Create zip file
print_info "Step 5: Creating zip file..."
cd "$OUTPUT_DIR"
zip -r -q "$OUTPUT_ZIP" .
cd - > /dev/null

# Verify zip was created
if [ ! -f "$OUTPUT_ZIP" ]; then
    print_error "Failed to create zip file"
    exit 1
fi

ZIP_SIZE=$(du -h "$OUTPUT_ZIP" | cut -f1)
print_info "Successfully created response handler package: $OUTPUT_ZIP (${ZIP_SIZE})"

# Show package contents summary
print_info "Package contents summary:"
unzip -l "$OUTPUT_ZIP" | head -20

print_info "Build completed successfully!"
print_info ""
print_info "Next steps:"
print_info "1. Update your Terraform configuration to use: $OUTPUT_ZIP"
print_info "2. Update the Lambda handler to: response_handler.handler"
