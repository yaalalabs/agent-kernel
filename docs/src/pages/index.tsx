import React from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import ArchitectureOverview from '@site/src/components/ArchitectureOverview';
import FAQ from '@site/src/components/FAQ';
import {
  Announcement,
  CapabilityRail,
  ClosingPanel,
  Deployment,
  Hero,
  Integrations,
  Levels,
  TrustMarks,
} from '@site/src/components/HomeSections';

/** The home page: the sections, in order. Each one lives in components/HomeSections. */
export default function Home(): JSX.Element {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title} - ${siteConfig.tagline}`}
      description="OAK is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, Google ADK, Smolagents, Pydantic AI, Microsoft Agent Framework, or the Claude Agent SDK to AWS, Azure, or GCP, with built-in messaging, memory, knowledge bases, guardrails, sandboxed code execution, and observability (Langfuse, OpenLLMetry, Pydantic Logfire, AWS CloudWatch)."
    >
      <Announcement />
      <Hero />
      <main>
        <TrustMarks />
        <CapabilityRail />
        <ArchitectureOverview />
        <Integrations />
        <Deployment />
        <Levels />
        <FAQ />
        <ClosingPanel />
      </main>
    </Layout>
  );
}
