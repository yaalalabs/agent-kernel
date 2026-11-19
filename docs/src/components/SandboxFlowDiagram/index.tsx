import React from "react";
import Link from "@docusaurus/Link";
import { TbPuzzle, TbTerminal2 } from "react-icons/tb";
// Simple Icons has no AWS mark, so that one comes from Font Awesome.
import { FaAws } from "react-icons/fa";
import { SiDocker, SiKubernetes } from "react-icons/si";
import styles from "./styles.module.css";

type ProviderNode = {
  key: string;
  name: string;
  icon: React.ReactNode;
  sub?: string;
  chip?: string;
  sandboxName: string;
  tier: string;
  link?: string;
};

const FRAMEWORKS =
  "OpenAI · LangGraph · CrewAI · Google ADK · Smolagents · Pydantic AI · Microsoft Agent Framework";

const PROVIDERS: ProviderNode[] = [
  {
    key: "local",
    name: "Local Subprocess Provider",
    icon: <TbTerminal2 />,
    sub: "host process · dev only",
    sandboxName: "Local Sandbox",
    tier: "no isolation",
    link: "/docs/advanced/sandbox#providers",
  },
  {
    key: "docker",
    name: "Docker Provider",
    icon: <SiDocker />,
    sub: "your Docker daemon",
    sandboxName: "Docker Sandbox",
    tier: "container",
    link: "/docs/advanced/sandbox#docker-setup",
  },
  {
    key: "kubernetes",
    name: "Kubernetes Provider",
    icon: <SiKubernetes />,
    sub: "pod per sandbox · RBAC boundary",
    sandboxName: "Kubernetes Pod",
    tier: "container",
    link: "/docs/advanced/sandbox#kubernetes-setup",
  },
  {
    key: "e2b",
    name: "E2B Provider",
    icon: (
      <img
        src="/img/integrations/e2b.png"
        alt=""
        className={`${styles.providerLogoImg} ${styles.providerLogoImgInvert}`}
      />
    ),
    sub: "E2B cloud · stateful kernel",
    sandboxName: "E2B Sandbox",
    tier: "micro-VM",
    link: "/docs/advanced/sandbox#e2b-setup",
  },
  {
    key: "daytona",
    name: "Daytona Provider",
    icon: (
      <img
        src="/img/integrations/daytona.png"
        alt=""
        className={styles.providerLogoImg}
      />
    ),
    sub: "Daytona cloud · snapshots",
    sandboxName: "Daytona Sandbox",
    tier: "container",
    link: "/docs/advanced/sandbox#daytona-setup",
  },
  {
    key: "ec2",
    name: "EC2 SSM Provider",
    icon: <FaAws />,
    sub: "existing instance via SSM",
    chip: "attached environment",
    sandboxName: "EC2 Instance",
    tier: "no isolation",
    link: "/docs/advanced/sandbox#ec2_ssm-setup",
  },
  {
    key: "byo",
    name: "Bring Your Own",
    icon: <TbPuzzle />,
    sub: "any SandboxProvider subclass",
    sandboxName: "Custom Sandbox",
    tier: "declared tier",
    link: "/docs/advanced/sandbox#bring-your-own-provider",
  },
];

const DETAIL_FOOTER = [
  {
    title: "Fail-closed policy",
    description:
      "Policy a provider cannot enforce is rejected under strict mode, never silently downgraded.",
  },
  {
    title: "Workload profiles",
    description:
      "per_session, per_call, and per_runtime scopes. Swap backends in config, never in code.",
  },
  {
    title: "Identity",
    description:
      "Run as the agent or as the authenticated end user via a PrincipalResolver.",
  },
  {
    title: "Task promotion",
    description:
      "A bounded wait, then a task id the agent polls with check_sandbox_task. Same contract on thread, embedded, and queue flavors.",
  },
] as const;

export default function SandboxFlowDiagram({
  detailed = false,
}: {
  detailed?: boolean;
}) {
  const providers = detailed
    ? PROVIDERS
    : PROVIDERS.filter((p) => p.key !== "local");

  const providerBoxInner = (p: ProviderNode) => (
    <>
      {detailed ? (
        <span className={styles.providerIcon} aria-hidden="true">
          {p.icon}
        </span>
      ) : null}
      <p className={styles.providerName}>{p.name}</p>
      {p.chip ? <span className={styles.providerChip}>{p.chip}</span> : null}
      {detailed && p.sub ? (
        <p className={styles.providerSub}>{p.sub}</p>
      ) : null}
    </>
  );

  return (
    <div className={styles.panel} role="group" aria-label="Sandbox execution flow">
      <p className={styles.scrollHint} aria-hidden="true">
        Scroll horizontally to see the full flow
      </p>

      <div className={styles.wrap}>
        <div
          className={`${styles.diagram} ${detailed ? styles.diagramDetailed : ""}`}
        >
          {/* Agent (a stack: one agent per framework) */}
          <div
            className={`${styles.node} ${styles.stack} ${styles.agentStack}`}
          >
            <div className={`${styles.stackFront} ${styles.agentNode}`}>
              <p className={styles.nodeTitle}>Agent</p>
              <p className={styles.nodeSub}>{FRAMEWORKS}</p>
              <span className={styles.agentChip}>any agentic framework</span>
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          {/* Sandbox tools */}
          <div className={`${styles.node} ${styles.chipNode}`}>
            <p className={styles.nodeTitle}>Sandbox Tools</p>
            {detailed ? (
              <p className={styles.nodeSub}>
                run_code · run_command · files · sessions · packages
              </p>
            ) : null}
          </div>

          <div className={styles.stem} aria-hidden="true" />

          {/* Session pill + security policy on the side */}
          <div className={styles.sessionRow}>
            <div className={styles.sessionSide} aria-hidden="true" />
            <div
              className={`${styles.node} ${styles.sessionNode}`}
            >
              <p className={styles.nodeTitle}>sandbox session</p>
              {detailed ? (
                <p className={styles.nodeSub}>
                  per_session · per_call · per_runtime
                </p>
              ) : null}
            </div>
            <div
              className={`${styles.node} ${styles.policyNode} ${styles.sessionSide}`}
            >
              <p className={styles.nodeTitle}>Security Policy</p>
              {detailed ? (
                <p className={styles.nodeSub}>
                  network · filesystem · cpu · memory · timeout · languages · packages
                </p>
              ) : null}
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          {/* Agent Kernel Execution Broker */}
          <div className={`${styles.node} ${styles.brokerNode}`}>
            <div className={styles.brokerRow}>
              <img
                src="/img/branding/oak-mark-orange.svg"
                alt=""
                className={styles.brokerLogo}
              />
              <div className={styles.brokerText}>
                <p className={styles.brokerEyebrow}>OAK</p>
                <p className={styles.brokerTitle}>Execution Broker</p>
              </div>
            </div>
            {detailed ? (
              <p className={styles.nodeSub}>
                thread · embedded · queue flavors
              </p>
            ) : null}
          </div>

          <div className={styles.stem} aria-hidden="true" />

          {/* Broker flavors: in-process lane beside the queue-decoupled lane */}
          <div className={styles.lanesRow}>
            <div className={styles.laneCol}>
              <div
                className={`${styles.node} ${styles.laneNode} ${styles.laneInProcess}`}
              >
                <p className={styles.laneEyebrow}>in-process</p>
                <p className={styles.nodeTitle}>thread · embedded</p>
                {detailed ? (
                  <p className={styles.nodeSub}>
                    runs inside the agent process · CLI and REST
                  </p>
                ) : null}
              </div>
              <div
                className={styles.laneDrop}
                aria-hidden="true"
              />
            </div>

            <div className={styles.laneCol}>
              <div
                className={`${styles.node} ${styles.laneNode} ${styles.laneQueue}`}
              >
                <p className={styles.laneEyebrow}>queue-decoupled</p>
                <div className={styles.chain}>
                  <span className={styles.chainBox}>Request queue</span>
                  <span className={styles.chainLink} aria-hidden="true" />
                  <span className={`${styles.chainBox} ${styles.chainBoxWorker}`}>
                    Sandbox Worker fleet
                  </span>
                </div>
                <div className={`${styles.chain} ${styles.chainReturn}`}>
                  <span className={styles.chainBox}>Response store</span>
                  <span
                    className={`${styles.chainLink} ${styles.chainLinkBack}`}
                    aria-hidden="true"
                  />
                  <span className={styles.chainBox}>Output queue</span>
                </div>
                {detailed ? (
                  <p className={styles.nodeSub}>
                    sqs · kafka · nats · pubsub · in_memory · bounded wait, then
                    check_sandbox_task
                  </p>
                ) : null}
              </div>
              <div
                className={styles.laneDrop}
                aria-hidden="true"
              />
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          {/* Provider fan-out */}
          <div
            className={styles.providersRow}
            style={{ "--cols": providers.length } as React.CSSProperties}
          >
            {providers.map((p, i) => (
              <div key={p.key} className={styles.providerCol}>
                {detailed && p.link ? (
                  <Link
                    to={p.link}
                    className={`${styles.node} ${styles.providerNode} ${styles.providerNodeLink}`}
                  >
                    {providerBoxInner(p)}
                  </Link>
                ) : (
                  <div
                    className={`${styles.node} ${styles.providerNode}`}
                  >
                    {providerBoxInner(p)}
                  </div>
                )}

                <div
                  className={styles.colStem}
                  aria-hidden="true"
                />

                <div
                  className={`${styles.node} ${styles.stack} ${styles.sandboxStack}`}
                >
                  <div className={`${styles.stackFront} ${styles.sandboxNode}`}>
                    <p className={styles.sandboxName}>{p.sandboxName}</p>
                    <span className={styles.tierChip}>{p.tier}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {detailed ? (
        <div className={styles.footer}>
          {DETAIL_FOOTER.map((item, i) => (
            <article
              key={item.title}
              className={styles.footerCard}
            >
              <h3 className={styles.footerTitle}>{item.title}</h3>
              <p className={styles.footerDesc}>{item.description}</p>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
