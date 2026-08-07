/**
 * Curated topics for the blog landing page filter.
 *
 * Posts are grouped into reader-facing topics by matching their frontmatter
 * tags (case-insensitive). A post can belong to several topics; a post whose
 * tags match no topic still appears under "All". When a new post introduces
 * tags that don't fit an existing topic, extend the relevant `tags` list here
 * (or add a new topic).
 */
export type BlogTopic = {
  label: string;
  slug: string;
  tags: string[];
};

export const BLOG_TOPICS: BlogTopic[] = [
  {
    label: 'Announcements',
    slug: 'announcements',
    tags: [
      'announcement',
      'opensource',
      'climate-impact-x',
      'production',
      'trade-surveillance',
    ],
  },
  {
    label: 'Cloud & Deployment',
    slug: 'cloud-deployment',
    tags: [
      'aws',
      'azure',
      'gcp',
      'google-cloud',
      'multi-cloud',
      'cloud-agnostic',
      'terraform',
      'cloud-run',
      'azure-functions',
      'container-apps',
      'portability',
      'serverless',
    ],
  },
  {
    label: 'Safety & Guardrails',
    slug: 'safety-guardrails',
    tags: [
      'guardrails',
      'guard-rails',
      'security',
      'safety',
      'pii',
      'moderation',
      'content-safety',
      'compliance',
      'walledai',
      'openai-guardrails',
      'aws-bedrock',
      'privacy',
    ],
  },
  {
    label: 'Observability',
    slug: 'observability',
    tags: [
      'observability',
      'tracing',
      'langfuse',
      'openllmetry',
      'traceloop',
      'monitoring',
    ],
  },
  {
    label: 'Integrations',
    slug: 'integrations',
    tags: [
      'slack',
      'whatsapp',
      'messenger',
      'messaging',
      'integrations',
      'chatbots',
      'telegram',
      'teams',
      'gmail',
      'instagram',
    ],
  },
  {
    label: 'Knowledge & Memory',
    slug: 'knowledge-memory',
    tags: [
      'knowledge-bases',
      'memory',
      'rag',
      'vector-store',
      'chromadb',
      'neo4j',
      'graph-database',
      'starburst',
      'self-evolving-agents',
      'cache',
    ],
  },
  {
    label: 'Developer Experience',
    slug: 'developer-experience',
    tags: [
      'skills',
      'cli',
      'claude',
      'cursor',
      'copilot',
      'windsurf',
      'developer-experience',
      'tools',
      'framework-agnostic',
      'hooks',
      'pre-hooks',
      'post-hooks',
      'execution-hooks',
      'langgraph',
      'crewai',
      'openai',
      'google-adk',
      'testing',
    ],
  },
  {
    label: 'Execution & Sandbox',
    slug: 'execution-sandbox',
    tags: [
      'sandbox',
      'code-execution',
      'execution-broker',
      'e2b',
      'docker',
      'daytona',
    ],
  },
];

type TagLike = {label: string};

export function postMatchesTopic(
  tags: readonly TagLike[],
  topic: BlogTopic,
): boolean {
  return tags.some((tag) => topic.tags.includes(tag.label.toLowerCase()));
}

export function topicsForPost(tags: readonly TagLike[]): BlogTopic[] {
  return BLOG_TOPICS.filter((topic) => postMatchesTopic(tags, topic));
}
