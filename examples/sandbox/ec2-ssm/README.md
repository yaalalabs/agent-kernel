# Sandbox — EC2 via SSM (attach to an existing runtime)

See [../README.md](../README.md) for the full set of sandbox examples.

This example demonstrates **mode-3 attach**: instead of provisioning a sandbox, the agent
executes code on an **EC2 instance you already own**, over AWS Systems Manager (SSM) Run
Command. The `ec2_ssm` provider is attach-only — `create` binds to the configured instance
and never provisions; `destroy` is a no-op (the provider never owns the host). Commands are
`ssm:SendCommand` (`AWS-RunShellScript`) invocations polled to completion; Python code is
wrapped in a `python3 - <<'EOF'` heredoc.

> **Warning:** isolation is **`none`**. Commands run directly on the instance with the SSM
> agent's OS permissions, and every policy dimension except the execution timeout is
> unenforceable (a non-default policy fails closed under `strict`). Point this at an
> instance you can afford to mutate.

## Identity

- **Agent mode** (this example): the default boto3 credential chain.
- **User mode** (`identity.mode: user` with a custom principal resolver, see
  [../identity/](../identity/)): the provider calls `sts:AssumeRole` on the principal's
  `role_arn` and, when `run_as` is set, executes each command as that OS user.

## Prerequisites

- An EC2 instance with the SSM agent registered (it appears under Systems Manager →
  Fleet Manager), with `python3` installed.
- AWS credentials allowing `ssm:SendCommand`, `ssm:GetCommandInvocation`,
  `ssm:DescribeInstanceInformation`, and `ssm:CancelCommand` on that instance.

## Run

    ./build.sh                 # or ./build.sh local
    export OPENAI_API_KEY=sk-...
    export AK_SANDBOX__PROFILES__EC2__EC2_SSM__ATTACH_TO=i-0123456789abcdef0
    uv run demo.py

Things to try in the CLI:

    Run a command in the sandbox to show the instance's hostname and OS.
    Compute the 30th Fibonacci number by running Python code.
    Create /tmp/ak-demo/notes.txt containing "hello", then show it in the next turn.  # same instance across turns

Because the workspace IS the instance, state persists across turns (and across sandbox
sessions — every session binds to the same host).

## Testing

This is the iteration-7 **manual evaluation checkpoint** for the attach model
(spec #494): it requires a real instance, so it is deliberately **not** part of the
automated e2e suite (`.github/test-config.yaml`). The provider's call shapes, heredoc
wrapping, identity mapping, and timeout behavior are covered by mocked-boto3 unit tests in
`ak-py/tests/test_sandbox_providers.py` (`-k ssm`).
