// @ts-check
// `@type` JSDoc annotations allow editor autocompletion and type checking
// (when paired with `@ts-check`).
// There are various equivalent ways to declare your Docusaurus config.
// See: https://docusaurus.io/docs/api/docusaurus-config

import { themes as prismThemes } from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Agent Kernel',
  tagline: 'The Operating System for Scalable & Compliant Enterprise AI Agents.',
  favicon: 'img/favicon.ico',
  url: 'https://kernel.yaala.ai',
  baseUrl: '/',

  // GitHub pages deployment config.
  organizationName: 'yaalalabs',
  projectName: 'agent-kernel',
  trailingSlash: false,

  clientModules: [
    './src/clientModules/ensureGtagGlobal.ts',
    './src/clientModules/scrollReveal.ts',
  ],

  onBrokenLinks: 'throw',

  // SEO head tags
  headTags: [
    // Preconnect to Google Fonts domains to reduce latency
    {
      tagName: 'link',
      attributes: {
        rel: 'preconnect',
        href: 'https://fonts.googleapis.com',
      },
    },
    {
      tagName: 'link',
      attributes: {
        rel: 'preconnect',
        href: 'https://fonts.gstatic.com',
        crossorigin: 'anonymous',
      },
    },
    // Preload the Google Fonts stylesheet
    {
      tagName: 'link',
      attributes: {
        rel: 'preload',
        as: 'style',
        href: 'https://fonts.googleapis.com/css2?family=Archivo:ital,wght@0,400;0,500;0,600;0,700;0,800;0,900;1,400;1,500;1,600&family=JetBrains+Mono:wght@400;500;600&display=swap',
      },
    },
    // Load stylesheet asynchronously to prevent render-blocking
    {
      tagName: 'link',
      attributes: {
        rel: 'stylesheet',
        href: 'https://fonts.googleapis.com/css2?family=Archivo:ital,wght@0,400;0,500;0,600;0,700;0,800;0,900;1,400;1,500;1,600&family=JetBrains+Mono:wght@400;500;600&display=swap',
        media: 'print',
        onload: "this.media='all'",
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'keywords',
        content: 'agent kernel, AI agent framework, AI agent runtime, AI agent deployment, AI agent platform, agentic AI development, multi-cloud AI agents, framework-agnostic AI, deploy AI agents, how to build AI agents, how to deploy AI agents to AWS, how to deploy AI agents to Azure, AI agent development platform open source, build AI agents with Python, LangGraph vs OpenAI agents vs CrewAI, AI agent Slack integration, WhatsApp AI bot, production AI agent deployment, AI agent testing framework, AI agent session management, AI agent guardrails, AI agent safety, agent-to-agent communication, MCP protocol, model context protocol, AI agent observability, AI agent tracing, agentkernel, Yaala Labs, LangGraph runtime, OpenAI Agents SDK deployment, Google ADK deployment, CrewAI deployment, serverless AI agents, containerized AI agents, multi-agent systems, AI agent orchestration, enterprise AI agents, Python AI agents, open source AI agent platform',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'author',
        content: 'Yaala Labs',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:title',
        content: 'Agent Kernel - The Operating System for Scalable & Compliant Enterprise AI Agents',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:description',
        content: 'Agent Kernel is the open-source operating system for building and deploying scalable, compliant enterprise AI agents. Works with any major AI framework (OpenAI, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit) and runs agents from multiple frameworks together in a single runtime. Deploys to AWS, Azure, or GCP with full Terraform modules and zero platform code, plus built-in messaging, memory, knowledge bases, guardrails, and observability.',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:type',
        content: 'website',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:url',
        content: 'https://kernel.yaala.ai',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:site_name',
        content: 'Agent Kernel by Yaala Labs',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'twitter:card',
        content: 'summary_large_image',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'twitter:title',
        content: 'Agent Kernel - The Operating System for Scalable & Compliant Enterprise AI Agents',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'twitter:description',
        content: 'The open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy production agents with OpenAI, LangGraph, CrewAI, or Google ADK to AWS, Azure, or GCP. Built-in messaging, memory, knowledge bases, guardrails, and observability.',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'robots',
        content: 'index, follow',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'language',
        content: 'English',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'revisit-after',
        content: '7 days',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'company',
        content: 'Yaala Labs',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'publisher',
        content: 'Yaala Labs',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'category',
        content: 'AI Infrastructure, Machine Learning, Software Development, Agentic AI',
      },
    },
    // Structured Data (JSON-LD) for better SEO
    {
      tagName: 'script',
      attributes: {
        type: 'application/ld+json',
      },
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Agent Kernel',
        applicationCategory: 'DeveloperApplication',
        description: 'Agent Kernel is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy production AI agents with any major framework (OpenAI, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit) and run multiple frameworks simultaneously in a single runtime. Deploy to AWS, Azure, or GCP with full Terraform modules.',
        operatingSystem: 'Linux, macOS, Windows',
        offers: {
          '@type': 'Offer',
          price: '0',
          priceCurrency: 'USD',
        },
        author: {
          '@type': 'Organization',
          name: 'Yaala Labs',
          url: 'https://www.yaalalabs.com',
        },
        url: 'https://kernel.yaala.ai',
        keywords: 'Agent Kernel, agentkernel, agent os, agent operating system, agent runtime, enterprise agents, agent deployment, compliant agents, scalable production agents, Yaala Labs, AI agent framework, AI agent runtime, AI agent deployment, agentic AI, enterprise AI agents, multi-cloud AI agents, framework-agnostic AI, LangGraph, OpenAI Agents, CrewAI, Google ADK, Smolagents, LiveKit, AWS, Azure, GCP, knowledge bases, AI agent guardrails, AI agent observability',
        featureList: [
          'Framework-neutral runtime: OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit',
          'Run multiple frameworks simultaneously in a single runtime',
          'Multi-cloud deployment to AWS, Azure, and GCP with full Terraform modules',
          'Built-in Slack, WhatsApp, Messenger, Instagram, Telegram, and Gmail integrations',
          'Session and memory management with Redis, DynamoDB, Cosmos DB, and in-memory backends',
          'Knowledge bases with Neo4j, Starburst Galaxy, ChromaDB, and custom SQL sources',
          'Execution hooks for guardrails, RAG, analytics, and moderation',
          'pytest-integrated agent testing framework',
          'Content safety guardrails via OpenAI, AWS Bedrock, and WalledAI',
          'LangFuse and OpenLLMetry observability',
          'MCP Server and A2A protocol support',
          'Open-source under the Apache 2.0 license',
        ],
      }),
    },
    {
      tagName: 'script',
      attributes: {
        type: 'application/ld+json',
      },
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'WebSite',
        name: 'Agent Kernel',
        alternateName: 'Agent Kernel by Yaala Labs',
        url: 'https://kernel.yaala.ai/',
      }),
    },
    {
      tagName: 'script',
      attributes: {
        type: 'application/ld+json',
      },
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        name: 'Primary Site Navigation',
        itemListElement: [
          {
            '@type': 'SiteNavigationElement',
            position: 1,
            name: 'Features',
            url: 'https://kernel.yaala.ai/features',
          },
          {
            '@type': 'SiteNavigationElement',
            position: 2,
            name: 'Use Cases',
            url: 'https://kernel.yaala.ai/use-cases',
          },
          {
            '@type': 'SiteNavigationElement',
            position: 3,
            name: 'Documentation',
            url: 'https://kernel.yaala.ai/docs',
          },
          {
            '@type': 'SiteNavigationElement',
            position: 4,
            name: 'Blog',
            url: 'https://kernel.yaala.ai/blog',
          },
        ],
      }),
    },
    {
      tagName: 'script',
      attributes: {
        type: 'application/ld+json',
      },
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'Organization',
        name: 'Yaala Labs',
        url: 'https://www.yaalalabs.com',
        logo: 'https://kernel.yaala.ai/img/logo.svg',
        sameAs: [
          'https://github.com/yaalalabs/agent-kernel',
        ],
        description: 'Yaala Labs is a technology company that builds next-generation cloud-native marketplace and capital markets infrastructure for both traditional and digital assets. Creator and maintainer of Agent Kernel, the open-source operating system for scalable, compliant enterprise AI agents.',
      }),
    },
  ],

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },
  themes: [
    '@docusaurus/theme-mermaid',
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        language: ['en'],
        highlightSearchTermsOnTargetPage: true,
        explicitSearchResultPath: true,
        docsRouteBasePath: '/docs',
      },
    ],
  ],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/docs',
          sidebarPath: './sidebars.js',
          editUrl:
            'https://github.com/yaalalabs/agent-kernel/tree/develop/docs/',
          includeCurrentVersion: true,
        },
        blog: {
          routeBasePath: 'blog',
          showReadingTime: true,
          authorsMapPath: 'authors.json',
          feedOptions: {
            type: ['rss', 'atom'],
            xslt: true,
          },
          editUrl:
            'https://github.com/yaalalabs/agent-kernel/tree/develop/docs/',
          onInlineTags: 'warn',
          onInlineAuthors: 'warn',
          onUntruncatedBlogPosts: 'warn',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
        gtag: {
          trackingID: 'G-TFXXDHX2H5',
          anonymizeIP: true,
        },
        sitemap: {
          lastmod: 'date',
          changefreq: 'weekly',
          priority: 0.5,
          ignorePatterns: [
            '/blog/tags/**',
            '/blog/authors/**',
            '/blog/archive/**',
            '/blog/page/**',
            '/search/**',
          ],
          filename: 'sitemap.xml',
          createSitemapItems: async (params) => {
            const { defaultCreateSitemapItems, ...rest } = params;
            const items = await defaultCreateSitemapItems(rest);
            return items
              .filter((item) => {
                const { url } = item;
                // Keep sitemap focused on canonical and high-value routes.
                if (url.includes('/blog/tags') || url.includes('/blog/blog') || url.includes('/blog/authors') || url.includes('/blog/archive') || url.includes('/blog/page/')) {
                  return false;
                }
                if (url.endsWith('/search') || url.includes('/search/')) {
                  return false;
                }
                // Exclude versioned/preview docs routes from sitemap to reduce noise.
                if (url.includes('/docs/next/') || url.match(/\/docs\/0\.[0-9]+\.[0-9]+/)) {
                  return false;
                }
                return true;
              })
              .map((item) => {
              // Set highest priority for key landing pages
              if (item.url === 'https://kernel.yaala.ai/' ||
                item.url === 'https://kernel.yaala.ai/docs' ||
                item.url === 'https://kernel.yaala.ai/docs/quick-start' ||
                item.url === 'https://kernel.yaala.ai/docs/installation' ||
                item.url === 'https://kernel.yaala.ai/features' ||
                item.url === 'https://kernel.yaala.ai/use-cases' ||
                item.url === 'https://kernel.yaala.ai/blog') {
                return { ...item, priority: 1.0, changefreq: 'daily' };
              }
              // High priority for blog posts
              if (item.url.includes('/blog/') && !item.url.includes('/blog/tags') && !item.url.includes('/blog/archive')) {
                return { ...item, priority: 0.8, changefreq: 'weekly' };
              }
              // Medium priority for documentation pages
              if (item.url.includes('/docs/')) {
                return { ...item, priority: 0.7, changefreq: 'weekly' };
              }
              // Lower priority for blog tags and archives
              if (item.url.includes('/blog/tags') || item.url.includes('/blog/archive') || item.url.includes('/blog/authors')) {
                return { ...item, priority: 0.3 };
              }
              return item;
            });
          },
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // SEO metadata
      metadata: [
        {
          name: 'description',
          content: 'Agent Kernel is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, or Google ADK to AWS, Azure, or GCP. Built-in messaging integrations, session and memory management, knowledge bases, testing framework, guardrails, and observability.',
        },
        {
          property: 'og:image',
          content: 'https://kernel.yaala.ai/img/card.png',
        },
        {
          name: 'twitter:image',
          content: 'https://kernel.yaala.ai/img/card.png',
        },
      ],
      image: 'img/card.png',
      navbar: {
        hideOnScroll: true,
        title: '',
        logo: {
          alt: 'Agent Kernel Logo',
          src: 'img/branding/agent-kernel-icon-horizontal-color-dark-bg.svg',
        },
        items: [
          { to: '/features', label: 'Features', position: 'left' },
          { to: '/use-cases', label: 'Use Cases', position: 'left' },
          {
            type: 'docSidebar',
            sidebarId: 'tutorialSidebar',
            position: 'left',
            label: 'Docs',
          },
          { to: '/blog', label: 'Blog', position: 'left' },
          {
            href: 'https://github.com/yaalalabs/agent-kernel',
            position: 'right',
            className: 'header-github-link',
            'aria-label': 'GitHub repository',
          },
          {
            type: 'docsVersionDropdown',
            position: 'right',
            dropdownActiveClassDisabled: true,
            dropdownItemsAfter: [],
            className: 'navbar-version-dropdown',
          },


        ],
      },
      footer: {
        style: 'dark',
        // Remove the logo key entirely: logo is now handled in FooterLayout
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'Getting Started', to: '/docs' },
              { label: 'Use Cases', to: '/use-cases' },
              { label: 'Architecture', to: '/docs/architecture/overview' },
              { label: 'API Reference', to: '/docs/api/rest-api' },
            ],
          },
          {
            title: 'Community',
            items: [
              { label: 'Discord', href: 'https://discord.gg/snrPzb46uu' },
              { label: 'GitHub', href: 'https://github.com/yaalalabs/agent-kernel' },
              { label: 'Issues', href: 'https://github.com/yaalalabs/agent-kernel/issues' },
            ],
          },
          {
            title: 'More',
            items: [
              { label: 'Blog', to: '/blog' },
              { label: 'PyPI', href: 'https://pypi.org/project/agentkernel/' },
              { label: 'Terraform', href: 'https://registry.terraform.io/modules/yaalalabs' },
            ],
          },
          {
            title: 'Legal',
            items: [
              { label: 'Privacy Policy', to: '/privacy-policy' },
              { label: 'Cookie Policy', to: '/cookie-policy' },
              { label: 'Terms of Use', to: '/terms-of-use' },
            ],
          },
        ],
        copyright: `© ${new Date().getFullYear()} <a href="https://yaalalabs.com" target="_blank" rel="noopener noreferrer">Yaala Labs</a>. All rights reserved.`,
      },
      prism: {
        theme: prismThemes.oneLight,
        darkTheme: prismThemes.oneDark,
        additionalLanguages: ['python', 'bash', 'json', 'yaml'],
      },
      colorMode: {
        defaultMode: 'dark',
        disableSwitch: true,
        respectPrefersColorScheme: false,
      },
      mermaid: {
        options: {
          look: "handDrawn",
          handDrawnSeed: 300
        },
      }
    }),
};

export default config;
