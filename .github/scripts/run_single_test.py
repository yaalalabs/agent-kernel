#!/usr/bin/env python3
"""
Run a single test.
Used by parallel GitHub Actions jobs for both integration tests and e2e tests.
"""

import argparse
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import json

CREWAI_DISABLE_TRACE_ENV = {
    "CREWAI_TRACING_ENABLED": "false",
    "CREWAI_TESTING": "true",
    "OTEL_SDK_DISABLED": "true",
    "CREWAI_DISABLE_TELEMETRY": "true",
}

def run_command(command: list[str], cwd: str = None, description: str = "", env: dict = None) -> bool:
    """Run a shell command and return success status."""
    try:
        print(f"\n{'='*80}")
        print(f"Running: {description}")
        print(f"Command: {' '.join(command)}")
        print(f"Directory: {cwd or 'current'}")
        print(f"{'='*80}\n")
        
        # Merge environment variables
        cmd_env = os.environ.copy()
        if env:
            cmd_env.update(env)
        
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=False,
            text=True,
            env=cmd_env
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed: {description}")
        print(f"Error: {e}")
        return False


def wait_for_endpoint(url: str, timeout: int = 300, interval: int = 10) -> bool:
    """Poll an endpoint until it responds with a non-5xx status.

    Containerized deployments return 5xx from the load balancer until the
    tasks are running and registered as healthy targets. A non-5xx response
    (including 4xx, since the invoke endpoint may reject GET) means traffic
    is reaching the application.
    """
    print(f"\n{'='*80}")
    print(f"Waiting for endpoint to become ready (POST): {url}")
    print(f"{'='*80}\n")

    body = json.dumps({"prompt": "readiness probe"}).encode()
    request_timeout = 35

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                print(f"✅ Endpoint ready (HTTP {resp.status})")
                return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                print(f"✅ Endpoint ready (HTTP {e.code})")
                return True
            print(f"⏳ Endpoint returned HTTP {e.code}, retrying in {interval}s...")
        except Exception as e:
            print(f"⏳ Endpoint not reachable ({e}), retrying in {interval}s...")
        time.sleep(interval)

    print(f"❌ Endpoint did not become ready within {timeout}s")
    return False


def run_simple_test(path: str) -> bool:
    """
    Run a simple test (cli, api, memory, containerized).
    These tests follow the same pattern: build.sh local, then pytest.
    """
    build_script = Path(path) / 'build.sh'
    
    if not build_script.exists():
        print(f"⚠️  Skipping {path} - no build.sh found")
        return True
    
    # Build
    if not run_command(
        ['./build.sh', 'local'],
        cwd=path,
        description=f"Building {path}",
        env=CREWAI_DISABLE_TRACE_ENV
    ):
        return False
    
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml', '--ignore-glob=dist*', '--ignore-glob=.terraform'],
        cwd=path,
        description=f"Testing {path}",
        env=CREWAI_DISABLE_TRACE_ENV
    )


def run_api_test(path: str) -> bool:
    """Run API example test."""
    return run_simple_test(path)


def run_memory_test(path: str) -> bool:
    """Run Memory example test."""
    return run_simple_test(path)


def run_cli_test(path: str) -> bool:
    """Run CLI example test."""
    return run_simple_test(path)


def run_containerized_test(path: str) -> bool:
    """Run containerized example test."""
    return run_simple_test(path)

def _read_tfvar(deploy_path: Path, key: str) -> str | None:
    """Read a scalar value from a deploy dir's terraform.tfvars (best-effort)."""
    tfvars = deploy_path / 'terraform.tfvars'
    if not tfvars.exists():
        return None
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*=\s*"?([^"\n]+?)"?\s*$')
    for line in tfvars.read_text().splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return None


def sweep_gcp_error_connectors(deploy_path: Path) -> None:
    region = _read_tfvar(deploy_path, 'region')
    product_alias = _read_tfvar(deploy_path, 'product_alias')
    env_alias = _read_tfvar(deploy_path, 'env_alias')
    if not (region and product_alias and env_alias):
        print("Skipping GCP connector sweep - could not resolve "
              "region/product_alias/env_alias from terraform.tfvars")
        return

    network = f"{product_alias}-{env_alias}-vpc"
    print(f"\n🧹 Sweeping ERROR-state VPC connectors on network '{network}' (region {region})...")
    try:
        result = subprocess.run(
            ['gcloud', 'compute', 'networks', 'vpc-access', 'connectors', 'list',
             f'--region={region}',
             f'--filter=state=ERROR AND network~{network}$',
             '--format=value(name)'],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Could not list VPC connectors (skipping sweep): {e}")
        return

    connectors = [line.strip().split('/')[-1] for line in result.stdout.splitlines() if line.strip()]
    if not connectors:
        print(" No ERROR-state connectors to clean up.")
        return

    for name in connectors:
        print(f"   Deleting ERROR connector: {name}")
        subprocess.run(
            ['gcloud', 'compute', 'networks', 'vpc-access', 'connectors', 'delete', name,
             f'--region={region}', '--quiet'],
            check=False,
        )
    print(" Connector sweep complete.")


def destroy_gcp_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None) -> bool:
    """Destroy GCP resources."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set Terraform automation flags for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    # Inject VPC configuration as Terraform variables if provided
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
                
        print(f"   TF_VAR_vpc_id={vpc_id}")
    if private_subnet_ids:
        try:
            parsed = json.loads(private_subnet_ids)
            tf_env['TF_VAR_private_subnet_ids'] = json.dumps(parsed)
            print(f"   TF_VAR_private_subnet_ids={json.dumps(parsed)}\n")

        except Exception:
            print("❌ Invalid subnet JSON")
            return False
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False

    sweep_gcp_error_connectors(deploy_path)

    # Destroy (already has -auto-approve flag)
    return run_command(
        ['terraform', 'destroy', '-auto-approve'],
        cwd=str(deploy_path),
        description=f"Destroying {path}",
        env=tf_env
    )

def deploy_gcp_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None) -> bool:
    """Deploy GCP resources only (without running tests)."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set Terraform automation flags for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    # Inject VPC configuration as Terraform variables if provided
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
                
        print("\n✅ Injecting VPC configuration as Terraform variables:")
        print(f"   TF_VAR_vpc_id={vpc_id}")    
    if private_subnet_ids:
        try:
            parsed = json.loads(private_subnet_ids)
            tf_env['TF_VAR_private_subnet_ids'] = json.dumps(parsed)
            print(f"   TF_VAR_private_subnet_ids={json.dumps(parsed)}\n")

        except Exception:
            print("❌ Invalid subnet JSON")
            return False
        
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if run_command(
            ['./deploy.sh', 'local'],
            cwd=str(deploy_path),
            description=f"Deploying {path} (attempt {attempt}/{max_attempts})",
            env=tf_env
        ):
            return True
        if attempt < max_attempts:
            print(f" Deploy attempt {attempt}/{max_attempts} failed; sweeping "
                  f"ERROR-state VPC connectors before retrying...")
            sweep_gcp_error_connectors(deploy_path)
    return False

def test_gcp_deployment(path: str, deploy_dir: str = 'deploy') -> bool:
    """Test an already deployed GCP resource."""
    deploy_path = Path(path) / deploy_dir
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    # Get agent_invoke_url terraform output and set AK_TEST_ENDPOINT
    try:
        print(f"\n{'='*80}")
        print("Retrieving agent_invoke_url terraform output")
        print(f"{'='*80}\n")
        
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'agent_invoke_url'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        agent_invoke_url = result.stdout.strip()
        if not agent_invoke_url:
            print("❌ Failed to retrieve agent_invoke_url: output was empty.")
            return False
        print(f"✅ agent_invoke_url: {agent_invoke_url}")
        
        # Set as environment variable for test
        test_env = {'AK_TEST_ENDPOINT': agent_invoke_url}
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to retrieve agent_invoke_url output: {e}")
        return False
    
    delete_config = run_command(
        ['rm', '-f', 'config.yaml'],
        cwd=path,
        description=f"Removing config.yaml for {path}"
    )
    
    if not delete_config:
        print(f"⚠️  Failed to remove config.yaml for {path}, but continuing with the test.")
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml', '--ignore-glob=dist*', '--ignore-glob=.terraform'],
        cwd=path,
        description=f"Testing {path}",
        env=test_env
    )
    
def destroy_azure_resources(path: str, deploy_dir: str = 'deploy', vnet_id: str = None, subnet_ids: str = None) -> bool:
    """Destroy Azure resources."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set environment variables for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    # Inject VNet configuration as environment variables if provided
    if vnet_id:
        tf_env['TF_VAR_vnet_id'] = vnet_id
        
        print("\n✅ Injecting VNet configuration as environment variables for destroy:")
        print(f"   TF_VAR_VNET_ID={vnet_id}")
        
    if subnet_ids:
        try:
            parsed = json.loads(subnet_ids)
            tf_env['TF_VAR_subnet_ids'] = json.dumps(parsed)
        except Exception:
            print("❌ Invalid subnet JSON")
            return False
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False
    
    # Destroy
    return run_command(
        ['terraform', 'destroy', '-auto-approve'],
        cwd=str(deploy_path),
        description=f"Destroying {path}",
        env=tf_env
    )

def deploy_azure_resources(path: str, deploy_dir: str = 'deploy', vnet_id: str = None, subnet_ids: str = None) -> bool:
    """Deploy Azure resources only (without running tests)."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set environment variables for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    
    # Inject VNet configuration as environment variables if provided
    if vnet_id:
        tf_env['TF_VAR_vnet_id'] = vnet_id
        
        print("\n✅ Injecting VNet configuration as environment variables:")
        print(f"   TF_VAR_vnet_id={vnet_id}")
    if subnet_ids:
        try:
            parsed = json.loads(subnet_ids)
            tf_env['TF_VAR_subnet_ids'] = json.dumps(parsed)
        except Exception:
            print("❌ Invalid subnet JSON")
            return False
    
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False

    # Deploy
    return run_command(
        ['./deploy.sh', 'local'],
        cwd=str(deploy_path),
        description=f"Deploying {path}",
        env=tf_env
    )

def test_azure_deployment(path: str, deploy_dir: str = 'deploy') -> bool:
    """Test an already deployed Azure resource."""
    deploy_path = Path(path) / deploy_dir
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    # Get agent_invoke_url terraform output and set AK_TEST_ENDPOINT
    try:
        print(f"\n{'='*80}")
        print("Retrieving agent_invoke_url terraform output")
        print(f"{'='*80}\n")
        
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'agent_invoke_url'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        agent_invoke_url = result.stdout.strip()
        if not agent_invoke_url:
            print("❌ Failed to retrieve agent_invoke_url: output was empty.")
            return False
        print(f"✅ agent_invoke_url: {agent_invoke_url}")
        
        # Set as environment variable for test
        test_env = {'AK_TEST_ENDPOINT': agent_invoke_url}
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to retrieve agent_invoke_url output: {e}")
        return False
    
    #remove the config.yaml till the issue with it is being solved
    
    delete_config = run_command(
        ['rm', '-f', 'config.yaml'],
        cwd=path,
        description=f"Removing config.yaml for {path}"
    )
    
    if not delete_config:
        print(f"⚠️  Failed to remove config.yaml for {path}, but continuing with the test.")
    # Test
    return run_command(
        ['uv', 'run', 'pytest', '-s', '--junitxml=pytest-report.xml', '--ignore-glob=dist*', '--ignore-glob=.terraform'],
        cwd=path,
        description=f"Testing {path}",
        env=test_env
    )

def _resolve_lambda_sg_ids(deploy_path: Path, region: str) -> list[str]:
    """Look up the example's Lambda security group ids by module-convention name."""
    product_alias = _read_tfvar(deploy_path, 'product_alias')
    env_alias = _read_tfvar(deploy_path, 'env_alias')
    if not (product_alias and env_alias):
        return []
    sg_names = [
        f"{product_alias}-{env_alias}-lambda-sg",
        f"{product_alias}-{env_alias}-authorizer-lambda-sg",
    ]
    try:
        result = subprocess.run(
            ['aws', 'ec2', 'describe-security-groups', '--region', region,
             '--filters', f'Name=group-name,Values={",".join(sg_names)}',
             '--query', 'SecurityGroups[].GroupId', '--output', 'text'],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [sg for sg in result.stdout.split() if sg and sg != 'None']


def _delete_lambda_functions_on_sgs(sg_ids: list[str], region: str) -> None:
    """Delete Lambda functions attached to sg_ids up front so AWS starts
    releasing their Hyperplane ENIs immediately."""
    wanted = set(sg_ids)
    try:
        res = subprocess.run(
            ['aws', 'lambda', 'list-functions', '--region', region,
             '--query', 'Functions[].{Name:FunctionName,SGs:VpcConfig.SecurityGroupIds}',
             '--output', 'json'],
            check=False, capture_output=True, text=True,
        )
        functions = json.loads(res.stdout or '[]')
    except Exception as e:  # never let cleanup crash the run
        print(f"   Could not list Lambda functions (ignored): {e}")
        return
    for fn in functions:
        if wanted.intersection(fn.get('SGs') or []):
            name = fn['Name']
            print(f"   Pre-deleting Lambda function {name} to start ENI release")
            subprocess.run(
                ['aws', 'lambda', 'delete-function', '--region', region,
                 '--function-name', name],
                check=False, capture_output=True, text=True,
            )


def _start_lambda_eni_sweeper(sg_ids: list[str], region: str, stop_event: threading.Event) -> threading.Thread:
    """Background loop that deletes detached Lambda ENIs on the given SGs."""
    def loop():
        while not stop_event.is_set():
            try:
                res = subprocess.run(
                    ['aws', 'ec2', 'describe-network-interfaces', '--region', region,
                     '--filters', f'Name=group-id,Values={",".join(sg_ids)}',
                     'Name=status,Values=available',
                     '--query', 'NetworkInterfaces[].NetworkInterfaceId', '--output', 'text'],
                    check=False, capture_output=True, text=True,
                )
                for eni in res.stdout.split():
                    print(f"   Deleting detached Lambda ENI {eni} to free SGs {sg_ids}")
                    subprocess.run(
                        ['aws', 'ec2', 'delete-network-interface', '--region', region,
                         '--network-interface-id', eni],
                        check=False, capture_output=True, text=True,
                    )
            except Exception as e:  # never let the sweeper thread crash the run
                print(f"   Lambda ENI sweep iteration error (ignored): {e}")
            stop_event.wait(15)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


def destroy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None) -> bool:
    """Destroy AWS resources."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set Terraform automation flags for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
    }
    
    # Inject VPC configuration as Terraform variables if provided
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
                
        print(f"   TF_VAR_vpc_id={vpc_id}")
    if private_subnet_ids:
        try:
            parsed = json.loads(private_subnet_ids)
            tf_env['TF_VAR_private_subnet_ids'] = json.dumps(parsed)
            print(f"   TF_VAR_private_subnet_ids={json.dumps(parsed)}\n")

        except Exception:
            print("❌ Invalid subnet JSON")
            return False
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False

    region = _read_tfvar(deploy_path, 'region') or os.environ.get('AWS_REGION')
    sweeper = None
    stop_event = threading.Event()
    if region:
        sg_ids = _resolve_lambda_sg_ids(deploy_path, region)
        if sg_ids:
            print(f"Starting Lambda ENI sweeper for security groups {sg_ids} "
                  f"(region {region}) to speed up destroy...")
            _delete_lambda_functions_on_sgs(sg_ids, region)
            sweeper = _start_lambda_eni_sweeper(sg_ids, region, stop_event)

    try:
        return run_command(
            ['terraform', 'destroy', '-auto-approve'],
            cwd=str(deploy_path),
            description=f"Destroying {path}",
            env=tf_env
        )
    finally:
        stop_event.set()
        if sweeper:
            sweeper.join(timeout=20)


def deploy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None) -> bool:
    """Deploy AWS resources only (without running tests)."""
    deploy_path = Path(path) / deploy_dir
    deploy_script = deploy_path / 'deploy.sh'
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    if not deploy_script.exists():
        print(f"⚠️  Skipping {path} - no deploy.sh found at {deploy_path}")
        return True
    
    # Set Terraform automation flags for non-interactive CI execution
    tf_env = {
        'TF_INPUT': '0',  # Disable interactive prompts
        'TF_CLI_ARGS_apply': '-auto-approve',  # Auto-approve applies
    }
    
    # Inject VPC configuration as Terraform variables if provided
    if vpc_id:
        tf_env['TF_VAR_vpc_id'] = vpc_id
        
        print("\n✅ Injecting VPC configuration as Terraform variables:")
        print(f"   TF_VAR_vpc_id={vpc_id}")    
    if private_subnet_ids:
        try:
            parsed = json.loads(private_subnet_ids)
            tf_env['TF_VAR_private_subnet_ids'] = json.dumps(parsed)
            print(f"   TF_VAR_private_subnet_ids={json.dumps(parsed)}\n")

        except Exception:
            print("❌ Invalid subnet JSON")
            return False
    # Initialize terraform if needed
    if not run_command(
        ['terraform', 'init', '-upgrade'],
        cwd=str(deploy_path),
        description=f"Terraform init for {path}",
        env=tf_env
    ):
        return False
    
    # Deploy
    return run_command(
        ['./deploy.sh', 'local'],
        cwd=str(deploy_path),
        description=f"Deploying {path}",
        env=tf_env
    )


def test_aws_deployment(path: str, deploy_dir: str = 'deploy') -> bool:
    """Test an already deployed AWS resource."""
    deploy_path = Path(path) / deploy_dir
    
    if not deploy_path.exists():
        print(f"⚠️  Skipping {path} - deploy directory not found: {deploy_path}")
        return True
    
    # Get agent_invoke_url terraform output and set AK_TEST_ENDPOINT
    try:
        print(f"\n{'='*80}")
        print("Retrieving agent_invoke_url terraform output")
        print(f"{'='*80}\n")
        
        result = subprocess.run(
            ['terraform', 'output', '-raw', 'agent_invoke_url'],
            cwd=str(deploy_path),
            check=True,
            capture_output=True,
            text=True
        )
        agent_invoke_url = result.stdout.strip()
        if not agent_invoke_url:
            print("❌ Failed to retrieve agent_invoke_url: output was empty.")
            return False
        print(f"✅ agent_invoke_url: {agent_invoke_url}")
        
        # Set as environment variable for test
        test_env = {'AK_TEST_ENDPOINT': agent_invoke_url}
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to retrieve agent_invoke_url output: {e}")
        return False

    # Containerized deployments need time for tasks to come up and pass
    # load balancer health checks before the endpoint serves traffic
    if not wait_for_endpoint(agent_invoke_url):
        return False

    # Install the LOCAL agentkernel wheel into the test client's venv before
    # running pytest. Without this, `uv run pytest` resolves agentkernel from
    # PyPI via uv.lock, so the client imports a published wheel that may not
    # match the local code under test (e.g. a config.yaml session type like
    # valkey that only exists locally fails validation at import). build.sh
    # local force-reinstalls from ../../../ak-py/dist (see deploy.sh local),
    # mirroring how the deployment package itself is built.
    if not run_command(
        ['./build.sh', 'local'],
        cwd=path,
        description=f"Building {path} with local agentkernel",
        env=CREWAI_DISABLE_TRACE_ENV
    ):
        return False

    # Test. Use --no-sync so uv does not re-sync the venv from uv.lock, which
    # would revert the local wheel installed above back to the PyPI version.
    return run_command(
        ['uv', 'run', '--no-sync', 'pytest', '-s', '--junitxml=pytest-report.xml', '--ignore-glob=dist*', '--ignore-glob=.terraform'],
        cwd=path,
        description=f"Testing {path}",
        env=test_env
    )


def main():
    parser = argparse.ArgumentParser(description='Run a single test')
    parser.add_argument('--type', required=True, 
                       choices=['api', 'memory', 'cli', 'containerized', 'aws-containerized', 'aws-serverless', 'azure-containerized', 'azure-serverless', 'gcp-containerized', 'gcp-serverless'],
                       help='Type of test to run')
    parser.add_argument('--path', required=True, help='Path to the test')
    parser.add_argument('--deploy-dir', default='deploy', help='Deploy directory for AWS tests')
    parser.add_argument('--action', choices=['deploy', 'test', 'destroy'], default='test', help='Action to perform')
    parser.add_argument('--vpc-id', default=None, help='VPC ID from base deployment')
    parser.add_argument('--private-subnet-ids', default=None, help='Private subnet IDs (JSON array) from base deployment')
    
    args = parser.parse_args()
    
    print(f"\n🚀 Running {args.action} for {args.type}: {args.path}\n")
    
    success = False
    
    if args.action == 'deploy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = deploy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['azure-serverless', 'azure-containerized']:
            success = deploy_azure_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['gcp-serverless', 'gcp-containerized']:
            success = deploy_gcp_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        else:
            print(f"⚠️  Deploy action not applicable for type: {args.type}")
            success = True
    elif args.action == 'destroy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = destroy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['azure-serverless', 'azure-containerized']:
            success = destroy_azure_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['gcp-serverless', 'gcp-containerized']:
            success = destroy_gcp_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        else:
            print(f"⚠️  Destroy action not applicable for type: {args.type}")
            success = True
    else:  # test action
        if args.type == 'api':
            success = run_api_test(args.path)
        elif args.type == 'memory':
            success = run_memory_test(args.path)
        elif args.type == 'cli':
            success = run_cli_test(args.path)
        elif args.type == 'containerized':
            success = run_containerized_test(args.path)
        elif args.type in ['aws-containerized', 'aws-serverless']:
            success = test_aws_deployment(args.path, args.deploy_dir)
        elif args.type in ['azure-containerized', 'azure-serverless']:
            success = test_azure_deployment(args.path, args.deploy_dir)
        elif args.type in ['gcp-containerized', 'gcp-serverless']:
            success = test_gcp_deployment(args.path, args.deploy_dir)
        else:
            print(f"  Test action not applicable for type: {args.type}")
            success = False
    
    if success:
        print(f"\n✅ SUCCESS: {args.path}")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED: {args.path}")
        sys.exit(1)


if __name__ == '__main__':
    main()
