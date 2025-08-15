#!/bin/bash

uv build --all
domain=yaalalabs
repository=agent-kernel

PUBLISH_TOKEN=$(aws codeartifact get-authorization-token \
  --domain $domain \
  --query authorizationToken \
  --output text)

PUBLISH_URL=$(aws codeartifact get-repository-endpoint --domain $domain --repository $repository --format pypi --query repositoryEndpoint --output text)

export UV_PUBLISH_USERNAME=aws
export UV_PUBLISH_PASSWORD="$PUBLISH_TOKEN"

read -r -p "Do you want to proceed with publishing? (y/n): " confirm
if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
    uv publish --publish-url "$PUBLISH_URL" --check-url "${PUBLISH_URL}"simple/
else
    echo "Publishing cancelled"
    exit 1
fi