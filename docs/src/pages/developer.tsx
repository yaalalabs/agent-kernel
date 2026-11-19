import React from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import PageHero from '@site/src/components/ui/PageHero';
import LevelStack from '@site/src/components/LevelStack';
import { ClosingPanel } from '@site/src/components/HomeSections';
import type { Step } from '@site/src/components/StepTimeline';
import { CodeSample, DocLinks, Journey, OtherLevels, PersonaSection } from '@site/src/components/PersonaKit';
import FrameworkSelector from '@site/src/components/FrameworkSelector';
import styles from './persona.module.css';

const STEPS: Step[] = [
  { id: 'write', label: 'Write' },
  { id: 'run', label: 'Run' },
  { id: 'configure', label: 'Configure' },
  { id: 'deploy', label: 'Deploy' },
  { id: 'test', label: 'Test' },
];

/* The snippets on this page are taken from the documentation (quick start, local deployment,
   configuration, deployment and testing guides). Keep them in step with it. */

const CLI_SESSION = `$ uv run python my_agent.py
AgentKernel CLI (type !help for commands or !quit to exit):
(kernel) >> Selected agent: assistant
(assistant) >> !list
Available agents:
  assistant

(assistant) >> What is 2 + 2?
(assistant) >> 2 + 2 = 4.`;

const REST_ENTRY = `from agentkernel.api import RESTAPI

# ... your agent and its module line, unchanged ...

if __name__ == "__main__":
    RESTAPI.run()`;

const REST_CALL = `uv add "agentkernel[api]"
uv run python my_agent.py

curl -X POST http://localhost:8000/api/v1/chat \\
  -H "Content-Type: application/json" \\
  -d '{"agent": "assistant", "prompt": "Hello!", "session_id": "test-123"}'`;

const CONFIG = `session:
  type: redis
  redis:
    url: redis://localhost:6379
    ttl: 604800  # 7 days in seconds

slack:
  agent: assistant
  bot_token_key: SLACK_BOT_TOKEN
  signing_secret_key: SLACK_SIGNING_SECRET

guardrail:
  input:
    enabled: true
    type: bedrock
    id: your-guardrail-id
    version: "1"

trace:
  enabled: true
  type: langfuse`;

const CAPABILITIES = [
  {
    title: 'Memory',
    line: 'Sessions start in memory and move to Redis, Valkey, DynamoDB, Cosmos DB or Firestore when you change session.type.',
    link: { label: 'Choose a memory backend', to: '/docs/core-concepts/memory-backends' },
  },
  {
    title: 'Channels',
    line: 'The slack block names the agent that answers and where its credentials are read from. Each channel also needs a short adapter in your entry point, shown in its guide.',
    link: { label: 'Integration guides', to: '/docs/integrations/overview' },
  },
  {
    title: 'Guardrails',
    line: 'Input and output checks run in the same pipeline as the agent, with OpenAI, Amazon Bedrock or Walled AI as the provider.',
    link: { label: 'Guardrails', to: '/docs/advanced/guardrails' },
  },
  {
    title: 'Tracing',
    line: 'One block sends every run to Langfuse, OpenLLMetry, Pydantic Logfire or CloudWatch, with no instrumentation in your code.',
    link: { label: 'Traceability', to: '/docs/advanced/traceability' },
  },
];

const TERRAFORM = `module "serverless_agents" {
    source    = "yaalalabs/ak-serverless/aws"
    providers = { aws = aws, docker = docker }

    prefix               = "ak-dev-quickstart"
    region               = var.region
    product_display_name = "AK Quick Start"

    request_handler = {
        function_name = "ak-quickstart"
        handler_path  = "lambda.handler"
        package_path  = "../dist"
        package_type  = "Image"
        memory_size   = 256
        timeout       = 45
    }
}`;

const HELM = `helm pull oci://ghcr.io/yaalalabs/charts/agent-kernel --untar
helm install ak oci://ghcr.io/yaalalabs/charts/agent-kernel \\
  -f agent-kernel/values-dev.yaml \\
  --set ioHandler.image.repository=<io image> \\
  --set agentRunner.image.repository=<runner image> \\
  --set image.tag=<tag>

kubectl port-forward service/ak-agent-kernel-io 8000:80`;

const TEST = `import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_client():
    test = Test("my_agent.py")
    await test.start()
    try:
        yield test
    finally:
        await test.stop()

@pytest.mark.order(1)
async def test_first_question(test_client):
    await test_client.send("Who won the 1996 cricket world cup?")
    await test_client.expect(["Sri Lanka won the 1996 cricket world cup."])

@pytest.mark.order(2)
async def test_follow_up_question(test_client):
    await test_client.send("Which country hosted the tournament?")
    await test_client.expect(["Co-hosted by India, Pakistan and Sri Lanka."])`;

export default function DeveloperPage(): JSX.Element {
  return (
    <Layout
      title="Open Agent Kernel for developers"
      description="The route from an empty folder to a deployed, tested AI agent with Open Agent Kernel: write, run, configure, deploy and test."
    >
      <PageHero
        art={<LevelStack active={1} />}
        label="Level 02 / Developers"
        title="Build your first agent, then ship it"
        lead="Open Agent Kernel (OAK) wraps the agent framework you already use and gives it an API, memory, channels and a way to production. This page walks the route from an empty folder to an agent that is deployed and tested."
        actions={
          <>
            <Link to="/docs/quick-start" className="ak-btn ak-btn--primary">
              Open the quick start
            </Link>
            <Link to="https://github.com/yaalalabs/agent-kernel" className="ak-link">
              View on GitHub
            </Link>
          </>
        }
      />
      <Journey steps={STEPS}>
        <PersonaSection
          id="write"
          index="01"
          label="Write"
          title="Write the agent in the framework you know"
          lead="OAK does not replace your framework. You define the agent the usual way, then hand it to a module."
        >
          <FrameworkSelector />
        </PersonaSection>

        <PersonaSection
          id="run"
          index="02"
          label="Run"
          title="Run it on your laptop, then call it over HTTP"
          lead="The same file runs as an interactive session or as an API server. Only the last line changes."
        >
          <div className={styles.grid2}>
            <div className={styles.stack}>
              <h3 className="ak-h3">In the terminal</h3>
              <p className="ak-body">
                The CLI opens a session with your agent. <code>!list</code> shows the registered agents,{' '}
                <code>!select</code> switches between them and <code>!quit</code> leaves.
              </p>
              <CodeSample title="Terminal" language="text">
                {CLI_SESSION}
              </CodeSample>
            </div>
            <div className={styles.stack}>
              <h3 className="ak-h3">As a REST API</h3>
              <p className="ak-body">
                Swap <code>CLI.main()</code> for <code>RESTAPI.run()</code> and the agent answers on{' '}
                <code>/api/v1/chat</code>, with sessions kept between calls.
              </p>
              <CodeSample title="my_agent.py" language="python">
                {REST_ENTRY}
              </CodeSample>
              <CodeSample title="Terminal" language="bash">
                {REST_CALL}
              </CodeSample>
            </div>
          </div>
          <div className={styles.blockSmall}>
            <DocLinks
              links={[
                { label: 'Local deployment', to: '/docs/deployment/local' },
                { label: 'REST API reference', to: '/docs/api/rest-api' },
                { label: 'MCP and A2A servers', to: '/docs/api/mcp-server' },
              ]}
            />
          </div>
        </PersonaSection>

        <PersonaSection
          id="configure"
          index="03"
          label="Configure"
          title="Switch capabilities on in config.yaml"
          lead="What you would otherwise build around an agent is a block of configuration. Every setting also has an environment variable, such as AK_SESSION__TYPE."
        >
          <div className={styles.split}>
            <ul className={styles.rows}>
              {CAPABILITIES.map((capability) => (
                <li key={capability.title} className={styles.row}>
                  <h3 className="ak-h4">{capability.title}</h3>
                  <p className="ak-body">{capability.line}</p>
                  <Link to={capability.link.to} className="ak-link">
                    {capability.link.label}
                  </Link>
                </li>
              ))}
            </ul>
            <div className={styles.stack}>
              <CodeSample title="config.yaml" language="yaml">
                {CONFIG}
              </CodeSample>
              <Link to="/docs/core-concepts/configuration" className="ak-link">
                Configuration reference
              </Link>
            </div>
          </div>
        </PersonaSection>

        <PersonaSection
          id="deploy"
          index="04"
          label="Deploy"
          title="Deploy with Terraform or Helm"
          lead="The agent code stays the same on every target. Terraform modules cover AWS, Azure and Google Cloud, and a Helm chart covers your own Kubernetes cluster."
        >
          <div className={styles.grid2}>
            <div className={styles.stack}>
              <h3 className="ak-h3">On your cloud</h3>
              <p className="ak-body">
                For AWS Lambda, end the file with <code>handler = Lambda.handler</code> in place of the CLI, point the
                module at your package, then run <code>terraform init</code> and <code>terraform apply</code>.
              </p>
              <CodeSample title="deploy/main.tf" language="hcl">
                {TERRAFORM}
              </CodeSample>
            </div>
            <div className={styles.stack}>
              <h3 className="ak-h3">On your own cluster</h3>
              <p className="ak-body">
                The chart runs the IO handler and the agent runner as separate deployments, so that each scales on
                its own.
              </p>
              <CodeSample title="Terminal" language="bash">
                {HELM}
              </CodeSample>
            </div>
          </div>
          <div className={styles.blockSmall}>
            <DocLinks
              links={[
                { label: 'All deployment targets', to: '/docs/deployment/overview' },
                { label: 'AWS serverless', to: '/docs/deployment/aws-serverless' },
                { label: 'Kubernetes with Helm', to: '/docs/deployment/onprem-kubernetes' },
              ]}
            />
          </div>
        </PersonaSection>

        <PersonaSection
          id="test"
          index="05"
          label="Test"
          title="Test it like any other code"
          lead="The test framework starts your agent, sends it messages and checks the replies, inside pytest."
        >
          <div className={styles.split}>
            <div className={styles.stack}>
              <ul className={styles.points}>
                <li>A session-scoped fixture keeps one conversation across ordered tests, so follow-up questions work</li>
                <li>Replies are compared by string score, by an LLM judge, or by score first and the judge as a fallback</li>
                <li>The same suite runs in CI against the CLI, the REST API or a container</li>
              </ul>
              <DocLinks
                links={[
                  { label: 'Testing overview', to: '/docs/testing/overview' },
                  { label: 'Automated testing', to: '/docs/testing/automated-testing' },
                ]}
              />
            </div>
            <CodeSample title="test_my_agent.py" language="python">
              {TEST}
            </CodeSample>
          </div>
        </PersonaSection>
      </Journey>

      <OtherLevels current="developer" />
      <ClosingPanel />
    </Layout>
  );
}
