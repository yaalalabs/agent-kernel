# Push the app to the EC2 instance created by `terraform apply` and start it.
# Run from deploy/ec2/ on Windows PowerShell:   ./deploy.ps1
# Prereqs: terraform applied; OpenSSH client (ships with Windows 11); the private
# key matching var.public_key_path loaded (default ~/.ssh/id_ed25519).

$ErrorActionPreference = "Stop"

$ip = terraform output -raw public_ip
$hostName = terraform output -raw hostname
$table = terraform output -raw dynamodb_table
$target = "ubuntu@$ip"
$src = Resolve-Path "$PSScriptRoot\..\.."

Write-Host "Deploying to $target ($hostName)..."

# 1. Ship the code (excluding heavyweight/local dirs).
$exclude = @(".venv", ".mypy_cache", ".pytest_cache", "__pycache__", "deploy", ".git")
$staging = Join-Path $env:TEMP "sarasavi-deploy"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory $staging | Out-Null
Get-ChildItem $src -Force | Where-Object { $exclude -notcontains $_.Name } |
    ForEach-Object { Copy-Item $_.FullName -Destination $staging -Recurse -Force }
scp -r "$staging\*" "${target}:/opt/sarasavi/"

# 2. Ensure prod session-store settings are present in the remote .env.
ssh $target @"
set -e
cd /opt/sarasavi
touch .env
grep -q '^AK_SESSION__TYPE=' .env || echo 'AK_SESSION__TYPE=dynamodb' >> .env
grep -q '^AK_SESSION__DYNAMODB__TABLE_NAME=' .env || echo 'AK_SESSION__DYNAMODB__TABLE_NAME=$table' >> .env
grep -q '^AWS_DEFAULT_REGION=' .env || echo 'AWS_DEFAULT_REGION=ap-south-1' >> .env
/usr/local/bin/uv sync --no-dev
"@

# 3. Caddyfile with the real hostname, then start everything.
ssh $target @"
set -e
sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
$hostName {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl restart caddy
sudo systemctl restart sarasavi
sleep 3
systemctl --no-pager --lines=5 status sarasavi || true
"@

Write-Host ""
Write-Host "Done. Webhook URL for the Meta dashboard:"
terraform output -raw webhook_url
Write-Host ""
Write-Host "NOTE: fill GOOGLE_API_KEY and AK_WHATSAPP__* in /opt/sarasavi/.env on the"
Write-Host "instance (ssh $target), then: sudo systemctl restart sarasavi"
