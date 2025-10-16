/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */

// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  // By default, Docusaurus generates a sidebar from the docs folder structure
  tutorialSidebar: [
    'intro',
    'installation',
    'quick-start',
    {
      type: 'category',
      label: 'Core Concepts',
      items: [
        'core-concepts/overview',
        'core-concepts/agent',
        'core-concepts/runner',
        'core-concepts/session',
        'core-concepts/module',
        'core-concepts/runtime',
      ],
    },
    {
      type: 'category',
      label: 'Architecture',
      items: [
        'architecture/overview',
        'architecture/execution-flow',
        'architecture/session-management',
        'architecture/memory-management',
      ],
    },
    {
      type: 'category',
      label: 'Framework Integration',
      items: [
        'frameworks/overview',
        'frameworks/openai',
        'frameworks/crewai',
        'frameworks/langgraph',
        'frameworks/google-adk',
      ],
    },
    {
      type: 'category',
      label: 'Deployment',
      items: [
        'deployment/overview',
        'deployment/local',
        'deployment/aws-serverless',
        'deployment/aws-containerized',
        'deployment/configuration',
      ],
    },
    {
      type: 'category',
      label: 'API & Integration',
      items: [
        'api/rest-api',
        'api/mcp-server',
        'api/a2a-server',
      ],
    },
    {
      type: 'category',
      label: 'Testing',
      items: [
        'testing/overview',
        'testing/cli-testing',
        'testing/automated-testing',
      ],
    },
    {
      type: 'category',
      label: 'Advanced Features',
      items: [
        'advanced/memory-management',
        'advanced/rbac',
        'advanced/traceability',
        'advanced/multi-agent',
      ],
    },
    {
      type: 'category',
      label: 'Examples',
      items: [
        'examples/basic-agent',
        'examples/multi-agent',
        'examples/custom-tools',
      ],
    },
  ],
};

export default sidebars;
