#!/bin/bash

set -e

# This script is used to provision the environment for the project.
# This is a template that will support both AWS and Azure deployments.
# The Build Scripts will be sourced such that, you can keep custom scripts as your process requires.

CUR_SCRIPT=$(readlink -f ${BASH_SOURCE[0]})
CUR_SCRIPT_DIR=$(dirname $CUR_SCRIPT)
CUR_FOLDER=$(basename $CUR_SCRIPT_DIR)


# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

CloudProvider=""
local=""

while [ $# -gt 0 ]; do
    case "$1" in
        --provider)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                print_error "--provider requires a value (aws|azure)"
                exit 1
            fi
            CloudProvider="$2"
            shift 2
            ;;
        --local)
            print_info "Build using local python source"
            local=local
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ "$CloudProvider" != "azure" ] && [ "$CloudProvider" != "aws" ]; then
    print_error "Invalid cloud provider: '$CloudProvider'. Use aws or azure."
    exit 1
fi

if [ "$CloudProvider" == "azure" ]; then
    print_header "Provisioning Azure environment"

    # Check for Azure CLI
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI not found. Please install it before continuing."
        print_info "Visit: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    fi

    # Check for Azure login
    if ! az account show &> /dev/null; then
        print_error "Azure login not found. Please login to your Azure account before continuing."
        print_info "Run: az login"
        exit 1
    fi

    # Get current subscription and user info
    SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    USER_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")
    TENANT_ID=$(az account show --query tenantId -o tsv)
    
    if [ -z "$USER_ID" ]; then
        print_warning "Could not retrieve user ID. You might be using a service principal."
        USER_ID=$(az account show --query user.name -o tsv)
    fi

    print_info "Current Azure Subscription: $SUBSCRIPTION_ID"
    print_info "Current User/Principal: $USER_ID"
    print_info "Tenant ID: $TENANT_ID"

    # Export ARM environment variables for Terraform
    export ARM_SUBSCRIPTION_ID="$SUBSCRIPTION_ID"
    
    print_success "Exported ARM_SUBSCRIPTION_ID: $ARM_SUBSCRIPTION_ID"

    # Function to check if user has a specific role
    check_role_assignment() {
        local role_name="$1"
        local scope="$2"
        local principal_id="$3"
        
        print_info "Checking role assignment: $role_name at scope: $scope"
        
        # Check if role assignment exists
        local role_exists=$(az role assignment list \
            --assignee "$principal_id" \
            --role "$role_name" \
            --scope "$scope" \
            --query "length(@)" -o tsv 2>/dev/null || echo "0")
        
        if [ "$role_exists" -gt 0 ]; then
            print_success "Role '$role_name' already assigned at scope: $scope"
            return 0
        else
            print_error "Role '$role_name' not found at scope: $scope"
            return 1
        fi
    }

    # Function to assign role with user confirmation
    assign_role_with_confirmation() {
        local role_name="$1"
        local scope="$2"
        local principal_id="$3"
        local description="$4"
        
        echo ""
        print_warning "Missing required role: $role_name"
        print_info "Description: $description"
        print_info "Scope: $scope"
        echo ""
        read -p "Would you like to assign this role automatically? (y/N): " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "Assigning role: $role_name..."
            if az role assignment create \
                --assignee "$principal_id" \
                --role "$role_name" \
                --scope "$scope" &>/dev/null; then
                print_success "Successfully assigned role: $role_name"
            else
                print_error "Failed to assign role: $role_name"
                print_warning "Please assign this role manually or contact your Azure administrator."
                return 1
            fi
        else
            print_warning "Please assign the role manually:"
            print_info "az role assignment create --assignee $principal_id --role \"$role_name\" --scope \"$scope\""
            return 1
        fi
    }

    # Check necessary Azure permissions
    print_header "Checking Azure permissions"
    
    # Subscription level permissions
    SUBSCRIPTION_SCOPE="/subscriptions/$SUBSCRIPTION_ID"
    
    # Only check for the role that's actually needed based on your experience
    declare -A REQUIRED_ROLES=(
        ["API Management Service Contributor"]="Required for creating and managing API Management services" #required for apim
    )

    # Check required roles
    missing_required_roles=0
    for role in "${!REQUIRED_ROLES[@]}"; do
        if ! check_role_assignment "$role" "$SUBSCRIPTION_SCOPE" "$USER_ID"; then
            if ! assign_role_with_confirmation "$role" "$SUBSCRIPTION_SCOPE" "$USER_ID" "${REQUIRED_ROLES[$role]}"; then
                missing_required_roles=1
            fi
        fi
    done

    # Check if Terraform is installed
    if ! command -v terraform &> /dev/null; then
        print_warning "Terraform not found. Please install Terraform to deploy infrastructure."
        print_info "Visit: https://developer.hashicorp.com/terraform/downloads"
    else
        print_success "Terraform found: $(terraform version | head -n1)"
    fi

    # Check Azure resource providers
    print_header "Checking Azure resource provider registrations"
    
    REQUIRED_PROVIDERS=(
        "Microsoft.Web"
        "Microsoft.Storage" 
        "Microsoft.DocumentDB"
        "Microsoft.Cache"
        "Microsoft.ApiManagement"
        "Microsoft.ContainerRegistry"
        "Microsoft.App"
        "Microsoft.Network"
        "Microsoft.Insights"
        "Microsoft.OperationalInsights"
    )

    for provider in "${REQUIRED_PROVIDERS[@]}"; do
        registration_state=$(az provider show --namespace "$provider" --query "registrationState" -o tsv 2>/dev/null || echo "NotFound")
        
        if [ "$registration_state" = "Registered" ]; then
            print_success "$provider: Registered"
        elif [ "$registration_state" = "Registering" ]; then
            print_warning "$provider: Currently registering..."
        else
            print_warning "$provider: Not registered"
            read -p "Would you like to register $provider? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                print_info "Registering $provider..."
                az provider register --namespace "$provider"
                print_success "$provider registration initiated (may take a few minutes to complete)"
            fi
        fi
    done

    if [ $missing_required_roles -eq 1 ]; then
        echo ""
        print_error "Missing required roles. Please assign the required roles and run this script again."
        exit 1
    fi

    print_success "Azure environment checks completed successfully!"
    echo ""
    print_info "Environment variables set:"
    print_info "  ARM_SUBSCRIPTION_ID=$ARM_SUBSCRIPTION_ID"
    echo ""
fi

if [ "$CloudProvider" == "aws" ]; then
    print_header "Provisioning AWS environment"
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI not found. Please install it before continuing."
        exit 1
    fi
    
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Please configure AWS credentials before continuing."
        exit 1
    fi
    
    print_success "AWS environment checks completed!"
fi

# Run build script if it exists
if [ -f "$CUR_FOLDER/deploy.sh" ]; then
    print_info "Running deploy.sh..."
    $CUR_FOLDER/deploy.sh $local
else
    print_warning "deploy.sh not found. Skipping"
    print_info "Make sure the sources are properly set up for cloud deployments to work."
fi

