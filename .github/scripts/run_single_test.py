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
import tempfile
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


def wait_for_backend(url: str, timeout: int = 600, interval: int = 10, required_answers: int = 2) -> bool:
    """Poll a POST-only agent invoke URL until the application behind the gateway answers.

    agent_invoke_url is a POST-only API Gateway route, so a GET is vacuous: the gateway answers it
    with its own 404 without contacting the backend. For containerized deployments `aws ecs wait
    services-stable` (deploy.sh) only means the task is RUNNING, not that uvicorn is listening;
    until it is, the ALB fails open to the target, the connection is refused and the gateway
    returns 502. So POST a body that is not valid JSON: the gateway forwards it and the backend
    rejects it before any agent runs (FastAPI 422, the Lambda router 500, or an auth layer
    401/403). Only 502/503/504 or no answer count as not ready; any other status means something
    behind the gateway answered. Two consecutive answers are required.
    """
    print(f"\n{'='*80}")
    print(f"Waiting for the backend behind {url} to answer")
    print(f"{'='*80}\n", flush=True)

    deadline = time.time() + timeout
    answers = 0
    while time.time() < deadline:
        request = urllib.request.Request(
            url, data=b"ak-readiness-probe", method="POST", headers={"Content-Type": "application/json"}
        )
        status = None
        try:
            with urllib.request.urlopen(request, timeout=15) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as e:
            print(f"⏳ Endpoint not reachable ({e}), retrying in {interval}s...", flush=True)
        if status is None or status in (502, 503, 504):
            answers = 0
            if status is not None:
                print(f"⏳ Gateway returned HTTP {status} (backend not serving yet), retrying in {interval}s...", flush=True)
        else:
            answers += 1
            print(f"✅ Backend answered HTTP {status} [{answers}/{required_answers}]", flush=True)
            if answers >= required_answers:
                return True
        time.sleep(interval)

    print(f"❌ Backend did not answer within {timeout}s", flush=True)
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


# Env-var-style keys copied from the job env into SSM for examples whose config.yaml uses the aws_ssm
# secret provider. Each lands at /ak/<prefix>/<key lowercased>, the path AWSSMSecretProvider reads.
SSM_SEEDED_KEYS = ["OPENAI_API_KEY"]


def seed_ssm_secrets(path: str, deploy_dir: str = 'deploy') -> bool:
    """Write SSM_SEEDED_KEYS from the environment to SSM when the example resolves secrets from aws_ssm."""
    import yaml

    config = yaml.safe_load((Path(path) / 'config.yaml').read_text()) or {}
    provider_type = ((config.get('secret') or {}).get('provider') or {}).get('type')
    if provider_type != 'aws_ssm':
        print(f"⏭️  Skipping SSM seeding - {path} does not use the aws_ssm secret provider")
        return True

    deploy_path = Path(path) / deploy_dir
    prefix = _read_tfvar(deploy_path, 'prefix')
    region = _read_tfvar(deploy_path, 'region')
    if not (prefix and region):
        print(f"❌ Could not resolve prefix/region from {deploy_path / 'terraform.tfvars'}")
        return False

    for key in SSM_SEEDED_KEYS:
        value = os.environ.get(key)
        if not value:
            print(f"❌ {key} is not set in the environment; cannot seed it to SSM")
            return False
        name = f"/ak/{prefix}/{key.lower()}"
        print(f"🔐 Seeding {name} (SecureString, region {region})")
        # Value goes via a private temp file, never argv, so it cannot show up in logs or the process list
        with tempfile.NamedTemporaryFile('w', suffix='.json') as request:
            json.dump({'Name': name, 'Value': value, 'Type': 'SecureString', 'Overwrite': True}, request)
            request.flush()
            try:
                subprocess.run(
                    ['aws', 'ssm', 'put-parameter', '--region', region,
                     '--cli-input-json', f'file://{request.name}'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to seed {name}: {e}")
                return False
    return True


def sweep_gcp_error_connectors(deploy_path: Path) -> None:
    region = _read_tfvar(deploy_path, 'region')
    prefix = _read_tfvar(deploy_path, 'prefix')
    if not (region and prefix):
        print("Skipping GCP connector sweep - could not resolve "
              "region/prefix from terraform.tfvars")
        return

    network = f"{prefix}-vpc"
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


def _gcp_firestore_module_name(deploy_path: Path) -> str | None:
    """Name of the root module block in deploy/main.tf that sets create_firestore_database = true."""
    main_tf = deploy_path / 'main.tf'
    if not main_tf.exists():
        return None
    # Top-level blocks start at column 0, so splitting on '\nmodule "' yields one chunk per module block.
    for chunk in ('\n' + main_tf.read_text()).split('\nmodule "')[1:]:
        name, _, body = chunk.partition('"')
        if re.search(r'^\s*create_firestore_database\s*=\s*true\b', body, re.MULTILINE):
            return name
    return None


def _gcp_orphan_firestore(deploy_path: Path) -> tuple[str, str, str] | None:
    """Return (project, database_id, address) when the example's Firestore database exists in GCP but not in state.

    google_firestore_database's post-create GET can 404 for a database the API has just created
    (hashicorp/terraform-provider-google#22533). The provider then drops it from state ("Root object was present,
    but now absent"), and because ak-gcp/common/modules/firestore names it after var.prefix, every later create gets
    409 "Database already exists" until the orphan is adopted or deleted.
    """
    module_name = _gcp_firestore_module_name(deploy_path)
    project = _read_tfvar(deploy_path, 'project_id')
    database_id = _read_tfvar(deploy_path, 'prefix')  # the firestore module uses var.prefix as the database id
    if not (module_name and project and database_id):
        return None
    try:
        described = subprocess.run(
            ['gcloud', 'firestore', 'databases', 'describe', f'--database={database_id}',
             f'--project={project}', '--format=value(name)'],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return None
    if described.returncode != 0 or not described.stdout.strip():
        return None
    address = f'module.{module_name}.module.firestore[0].google_firestore_database.db'
    # List the whole state rather than the address: `terraform state list <addr>` exits 1 both for "not in state"
    # and for backend/auth errors, and treating an unreadable state as "not in state" would let the purge delete a
    # database Terraform still tracks. Only a readable state without the address, or no state at all, counts.
    in_state = subprocess.run(['terraform', 'state', 'list'],
                              cwd=str(deploy_path), capture_output=True, text=True)
    if in_state.returncode == 0:
        if address in in_state.stdout.split():
            return None
    elif 'No state file was found' not in in_state.stdout + in_state.stderr:
        print(f" ⚠️  Could not read Terraform state to check Firestore database '{database_id}'; leaving it alone.\n"
              f"{in_state.stderr.strip()}", flush=True)
        return None
    return project, database_id, address


def adopt_gcp_orphan_firestore(deploy_path: Path, tf_env: dict) -> None:
    """Import an orphaned Firestore database so the next apply reuses it instead of failing with 409."""
    orphan = _gcp_orphan_firestore(deploy_path)
    if not orphan:
        return
    project, database_id, address = orphan
    print(f"\n🧹 Firestore database '{database_id}' exists but is not in Terraform state; importing it...", flush=True)
    import_env = dict(tf_env)
    # deploy.sh passes openai_api_key with -var from OPENAI_API_KEY; import evaluates the root module, so it needs it too.
    if 'TF_VAR_openai_api_key' not in os.environ and os.environ.get('OPENAI_API_KEY'):
        import_env['TF_VAR_openai_api_key'] = os.environ['OPENAI_API_KEY']
    run_command(
        ['terraform', 'import', '-input=false', address, f'projects/{project}/databases/{database_id}'],
        cwd=str(deploy_path),
        description=f"Importing orphaned Firestore database {database_id}",
        env=import_env,
    )


def purge_gcp_orphan_firestore(deploy_path: Path) -> None:
    """Delete a Firestore database that terraform destroy could not see, so it cannot block the next run."""
    orphan = _gcp_orphan_firestore(deploy_path)
    if not orphan:
        return
    project, database_id, _ = orphan
    print(f"\n🧹 Deleting orphaned Firestore database '{database_id}' (not in Terraform state)...", flush=True)
    subprocess.run(
        ['gcloud', 'firestore', 'databases', 'delete', f'--database={database_id}',
         f'--project={project}', '--quiet'],
        check=False,
    )


def sweep_azure_orphan_container_env(deploy_path: Path, tf_env: dict) -> None:
    """Self-heal a Container Apps environment that exists in Azure but not in terraform state.

    A create that fails asynchronously (e.g. ManagedEnvironmentCapacityHeavyUsageError) leaves the
    environment behind in provisioningState=Failed without recording it in state, and every later
    apply then fails with "already exists - needs to be imported". A Failed/Canceled orphan is
    deleted (it can host nothing); a Succeeded orphan is imported so terraform reconciles it. Any
    other state (InProgress, Deleting, ...) may belong to an overlapping run, so it is left alone.
    """
    rg = _read_tfvar(deploy_path, 'resource_group_name')
    prefix = _read_tfvar(deploy_path, 'prefix')
    if not (rg and prefix):
        print("Skipping Container Apps env sweep - could not resolve resource_group_name/prefix")
        return
    address = 'module.containerd_agent.azurerm_container_app_environment.env'
    name = f"{prefix}-env"

    # List the whole state: `terraform state list <addr>` also exits 1 when the address is merely absent.
    state = subprocess.run(['terraform', 'state', 'list'], cwd=str(deploy_path),
                           capture_output=True, text=True, env={**os.environ, **tf_env})
    if state.returncode == 0:
        if address in state.stdout.split():
            return  # tracked by terraform; nothing to heal
    elif 'No state file was found' not in state.stdout + state.stderr:
        print(f"Skipping Container Apps env sweep - could not read terraform state: {state.stderr.strip()}")
        return

    try:
        show = subprocess.run(['az', 'containerapp', 'env', 'show', '-g', rg, '-n', name,
                               '--query', '{id:id,state:properties.provisioningState}', '-o', 'json'],
                              capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"Skipping Container Apps env sweep - az lookup failed: {e}")
        return
    if show.returncode != 0:
        return  # not found - normal fresh deploy
    env = json.loads(show.stdout)
    print(f"\n🧹 Container Apps env {name} exists but is not in terraform state "
          f"(provisioningState={env['state']})")
    if env['state'] in ('Failed', 'Canceled'):
        deleted = run_command(['az', 'containerapp', 'env', 'delete', '-g', rg, '-n', name, '--yes'],
                              description=f"Deleting orphaned {name}")
        if not deleted:
            print(f"::warning::Could not delete orphaned {name}; the apply will fail with 'already exists'")
    elif env['state'] == 'Succeeded':
        run_command(['terraform', 'import', address, env['id']], cwd=str(deploy_path),
                    description=f"Importing orphaned {name}", env=tf_env)
    else:
        print(f"::warning::Leaving {name} alone (provisioningState={env['state']}); another run may own it")


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
    destroyed = run_command(
        ['terraform', 'destroy', '-auto-approve'],
        cwd=str(deploy_path),
        description=f"Destroying {path}",
        env=tf_env
    )
    if destroyed:
        # Only after a clean destroy: a failed destroy leaves state partly populated, and the next run's
        # adopt_gcp_orphan_firestore can recover any orphan without deleting anything.
        purge_gcp_orphan_firestore(deploy_path)
    return destroyed

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
        adopt_gcp_orphan_firestore(deploy_path, tf_env)
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
    
    # Destroy. Retry: a freshly created APIM service intermittently answers child-resource reads
    # with 401/422 (and deletes with 409 ServiceLocked) for a short while after provisioning.
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        if run_command(
            ['terraform', 'destroy', '-auto-approve'],
            cwd=str(deploy_path),
            description=f"Destroying {path} (attempt {attempt}/{max_attempts})",
            env=tf_env
        ):
            return True
        if attempt < max_attempts:
            print(f"Destroy attempt {attempt}/{max_attempts} failed; retrying in 120s...")
            time.sleep(120)
    return False

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

    # Matches both the registry source and the local path inject_dependencies.py rewrites it to in CI.
    main_tf = deploy_path / 'main.tf'
    main_src = main_tf.read_text() if main_tf.exists() else ''
    if 'ak-containerized/azurerm' in main_src or 'ak-azure/containerized' in main_src:
        sweep_azure_orphan_container_env(deploy_path, tf_env)

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
            print(f"Deploy attempt {attempt}/{max_attempts} failed; retrying in 60s...", flush=True)
            time.sleep(60)
    return False

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
    prefix = _read_tfvar(deploy_path, 'prefix')
    if not prefix:
        return []
    sg_names = [
        f"{prefix}-request-handler-sg",
        f"{prefix}-agent-runner-sg",
        f"{prefix}-response-handler-sg",
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


def destroy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None, request_handler_security_group_id: str = None, agent_runner_security_group_id: str = None, response_handler_security_group_id: str = None) -> bool:
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
    if request_handler_security_group_id:
        tf_env['TF_VAR_request_handler_security_group_id'] = request_handler_security_group_id
        print(f"   TF_VAR_request_handler_security_group_id={request_handler_security_group_id}")
    if agent_runner_security_group_id:
        tf_env['TF_VAR_agent_runner_security_group_id'] = agent_runner_security_group_id
        print(f"   TF_VAR_agent_runner_security_group_id={agent_runner_security_group_id}")
    if response_handler_security_group_id:
        tf_env['TF_VAR_response_handler_security_group_id'] = response_handler_security_group_id
        print(f"   TF_VAR_response_handler_security_group_id={response_handler_security_group_id}")
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


def deploy_aws_resources(path: str, deploy_dir: str = 'deploy', vpc_id: str = None, private_subnet_ids: str = None, request_handler_security_group_id: str = None, agent_runner_security_group_id: str = None, response_handler_security_group_id: str = None) -> bool:
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
    if request_handler_security_group_id:
        tf_env['TF_VAR_request_handler_security_group_id'] = request_handler_security_group_id
        print(f"   TF_VAR_request_handler_security_group_id={request_handler_security_group_id}")
    if agent_runner_security_group_id:
        tf_env['TF_VAR_agent_runner_security_group_id'] = agent_runner_security_group_id
        print(f"   TF_VAR_agent_runner_security_group_id={agent_runner_security_group_id}")
    if response_handler_security_group_id:
        tf_env['TF_VAR_response_handler_security_group_id'] = response_handler_security_group_id
        print(f"   TF_VAR_response_handler_security_group_id={response_handler_security_group_id}")
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
    # load balancer health checks before the endpoint serves traffic.
    if not wait_for_backend(agent_invoke_url):
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
    parser.add_argument('--action', choices=['deploy', 'test', 'destroy', 'seed-secrets'], default='test', help='Action to perform')
    parser.add_argument('--vpc-id', default=None, help='VPC ID from base deployment')
    parser.add_argument('--private-subnet-ids', default=None, help='Private subnet IDs (JSON array) from base deployment')
    parser.add_argument('--request-handler-security-group-id', default=None, help='Request handler security group ID from base deployment; sets TF_VAR_request_handler_security_group_id (used for aws-serverless jobs)')
    parser.add_argument('--agent-runner-security-group-id', default=None, help='Agent runner security group ID from base deployment; sets TF_VAR_agent_runner_security_group_id (used for the queue-mode aws-serverless jobs)')
    parser.add_argument('--response-handler-security-group-id', default=None, help='Response handler security group ID from base deployment; sets TF_VAR_response_handler_security_group_id (used for the queue-mode aws-serverless jobs)')

    args = parser.parse_args()

    print(f"\n🚀 Running {args.action} for {args.type}: {args.path}\n")

    success = False

    if args.action == 'seed-secrets':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = seed_ssm_secrets(args.path, args.deploy_dir)
        else:
            print(f"⚠️  Seed-secrets action not applicable for type: {args.type}")
            success = True
    elif args.action == 'deploy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = deploy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids, args.request_handler_security_group_id, args.agent_runner_security_group_id, args.response_handler_security_group_id)
        elif args.type in ['azure-serverless', 'azure-containerized']:
            success = deploy_azure_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        elif args.type in ['gcp-serverless', 'gcp-containerized']:
            success = deploy_gcp_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids)
        else:
            print(f"⚠️  Deploy action not applicable for type: {args.type}")
            success = True
    elif args.action == 'destroy':
        if args.type in ['aws-containerized', 'aws-serverless']:
            success = destroy_aws_resources(args.path, args.deploy_dir, args.vpc_id, args.private_subnet_ids, args.request_handler_security_group_id, args.agent_runner_security_group_id, args.response_handler_security_group_id)
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
