import React, { type ReactNode } from 'react';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import { FaAws, FaMicrosoft } from 'react-icons/fa';
import { SiGooglecloud, SiHelm, SiKubernetes, SiTerraform } from 'react-icons/si';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import Reveal from '@site/src/components/ui/Reveal';
import styles from './deployment.module.css';

/* ─── Deployment ──────────────────────────────────────────────────────────
   Four targets, each with the modes it supports and the published module or
   chart that provisions it. */

type Target = {
  icon: ReactNode;
  name: string;
  description: string;
  modes: string[];
  modules: Array<{ kind: 'terraform' | 'helm'; name: string; url: string }>;
};

const TARGETS: Target[] = [
  {
    icon: <FaAws />,
    name: 'Amazon AWS',
    description: 'Serverless or containerized deployments with Terraform modules.',
    modes: ['AWS Lambda (serverless)', 'AWS ECS on Fargate (containerized)'],
    modules: [
      { kind: 'terraform', name: 'AWS serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-serverless/aws' },
      { kind: 'terraform', name: 'AWS containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/aws' },
    ],
  },
  {
    icon: <SiGooglecloud />,
    name: 'Google Cloud',
    description: 'Cloud Run serverless or containerized deployments with Firestore session storage.',
    modes: ['Cloud Run (serverless)', 'Cloud Run (containerized)'],
    modules: [
      { kind: 'terraform', name: 'GCP serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-serverless/google' },
      { kind: 'terraform', name: 'GCP containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/google' },
    ],
  },
  {
    icon: <FaMicrosoft />,
    name: 'Microsoft Azure',
    description: 'Container Apps serverless or containerized deployments with Cosmos DB session storage.',
    modes: [
      'Container Apps (serverless)',
      'Container Apps (containerized)',
      'Queue mode over Service Bus',
    ],
    // One module serves both: the serverless variant is the same Container Apps deployment with
    // `container_min_replicas = 0`.
    modules: [
      { kind: 'terraform', name: 'Azure serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/azurerm' },
      { kind: 'terraform', name: 'Azure containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/azurerm' },
    ],
  },
  {
    icon: <SiKubernetes />,
    name: 'On-prem Kubernetes',
    description: 'The official Helm chart, for any Kubernetes cluster.',
    modes: [
      'Bare metal or a self-hosted cluster',
      'AWS EKS (Pod Identity, with SQS, NATS or Kafka)',
      'KEDA autoscaling on queue depth',
      'Air-gapped installs (mirrored images)',
    ],
    modules: [
      { kind: 'helm', name: 'Helm chart', url: 'https://github.com/yaalalabs/agent-kernel/pkgs/container/charts%2Fagent-kernel' },
    ],
  },
];

export function Deployment(): JSX.Element {
  return (
    <section id="deployment" className="ak-section">
      <div className="ak-container">
        <SectionHeader
          index="04"
          label="Deployment"
          title="Deploy anywhere"
          lead="Run the same agent code on AWS, GCP, Azure or your own Kubernetes cluster. Terraform modules and a Helm chart are included."
        />

        <div className={styles.grid}>
          {TARGETS.map((target, index) => (
            <Reveal key={target.name} delay={index * 70} className={clsx('ak-card', styles.card)}>
              <div className={styles.head}>
                <span className={styles.icon} aria-hidden="true">
                  {target.icon}
                </span>
                <h3 className="ak-h4">{target.name}</h3>
              </div>
              <p className="ak-small">{target.description}</p>
              <ul className={styles.modes}>
                {target.modes.map((mode) => (
                  <li key={mode}>{mode}</li>
                ))}
              </ul>
              <div className={styles.modules}>
                {target.modules.map((module) => (
                  <Link key={module.name} to={module.url} className={styles.module} target="_blank" rel="noopener noreferrer">
                    {module.kind === 'helm' ? <SiHelm aria-hidden="true" /> : <SiTerraform aria-hidden="true" />}
                    <span>{module.name}</span>
                  </Link>
                ))}
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
