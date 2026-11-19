// @ts-check
// `@type` JSDoc annotations allow editor autocompletion and type checking
// (when paired with `@ts-check`).
// There are various equivalent ways to declare your Docusaurus config.
// See: https://docusaurus.io/docs/api/docusaurus-config

import { themes as prismThemes } from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Open Agent Kernel',
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
        content: 'open agent kernel, OAK, agent kernel, AI agent framework, AI agent runtime, AI agent deployment, AI agent platform, agentic AI development, multi-cloud AI agents, framework-agnostic AI, deploy AI agents, how to build AI agents, how to deploy AI agents to AWS, how to deploy AI agents to Azure, AI agent development platform open source, build AI agents with Python, LangGraph vs OpenAI agents vs CrewAI, AI agent Slack integration, WhatsApp AI bot, production AI agent deployment, AI agent testing framework, AI agent session management, AI agent guardrails, AI agent safety, agent-to-agent communication, MCP protocol, model context protocol, AI agent observability, AI agent tracing, agentkernel, Yaala Labs, LangGraph runtime, OpenAI Agents SDK deployment, Google ADK deployment, CrewAI deployment, serverless AI agents, containerized AI agents, multi-agent systems, AI agent orchestration, enterprise AI agents, Python AI agents, open source AI agent platform',
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
        content: 'Open Agent Kernel (OAK) - The Operating System for Scalable & Compliant Enterprise AI Agents',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:description',
        content: 'Open Agent Kernel (OAK) is the open-source operating system for building and deploying scalable, compliant enterprise AI agents. Works with any major AI framework (OpenAI, LangGraph, CrewAI, Google ADK, Smolagents) and runs agents from multiple frameworks together in a single runtime. Deploys to AWS, Azure, or GCP with full Terraform modules and zero platform code, plus the LiveKit voice integration, built-in messaging, memory, knowledge bases, guardrails, and observability.',
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
        content: 'Open Agent Kernel by Yaala Labs',
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
        content: 'Open Agent Kernel (OAK) - The Operating System for Scalable & Compliant Enterprise AI Agents',
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
        name: 'Open Agent Kernel',
        alternateName: ['OAK', 'Agent Kernel'],
        applicationCategory: 'DeveloperApplication',
        description: 'Open Agent Kernel (OAK) is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy production AI agents with any major framework (OpenAI, LangGraph, CrewAI, Google ADK, Smolagents) and run multiple frameworks simultaneously in a single runtime. Connect agents to LiveKit rooms for realtime voice. Deploy to AWS, Azure, or GCP with full Terraform modules.',
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
        keywords: 'Open Agent Kernel, OAK, Agent Kernel, agentkernel, agent os, agent operating system, agent runtime, enterprise agents, agent deployment, compliant agents, scalable production agents, Yaala Labs, AI agent framework, AI agent runtime, AI agent deployment, agentic AI, enterprise AI agents, multi-cloud AI agents, framework-agnostic AI, LangGraph, OpenAI Agents, CrewAI, Google ADK, Smolagents, LiveKit, AWS, Azure, GCP, knowledge bases, AI agent guardrails, AI agent observability',
        featureList: [
          'Framework-neutral runtime: OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents',
          'Realtime voice through the LiveKit integration for OpenAI Agents SDK and Google ADK agents',
          'Run multiple frameworks simultaneously in a single runtime',
          'Multi-cloud deployment to AWS, Azure, and GCP with full Terraform modules',
          'Built-in Slack, WhatsApp, Messenger, Instagram, Telegram, Microsoft Teams, and Gmail integrations',
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
        name: 'Open Agent Kernel',
        alternateName: ['OAK', 'Agent Kernel', 'Open Agent Kernel by Yaala Labs'],
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
        description: 'Yaala Labs is a technology company that builds next-generation cloud-native marketplace and capital markets infrastructure for both traditional and digital assets. Creator and maintainer of Open Agent Kernel (OAK), the open-source operating system for scalable, compliant enterprise AI agents.',
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
          blogTitle: 'Open Agent Kernel Blog',
          blogDescription:
            'Product announcements, engineering deep dives, and stories from the Open Agent Kernel team.',
          // All posts render on one landing page so topic filtering works client-side.
          postsPerPage: 'ALL',
          blogSidebarCount: 0,
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
          customCss: ['./src/css/custom.css', './src/css/blog-medium.css'],
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
                // Keep only the latest docs (the /docs/next routes) in the sitemap;
                // drop versioned docs routes to avoid duplicate/stale entries.
                if ((url.endsWith('/docs') || url.includes('/docs/')) && !url.includes('/docs/next')) {
                  return false;
                }
                return true;
              })
              .map((item) => {
              // Set highest priority for key landing pages
              if (item.url === 'https://kernel.yaala.ai/' ||
                item.url === 'https://kernel.yaala.ai/docs/next' ||
                item.url === 'https://kernel.yaala.ai/docs/next/quick-start' ||
                item.url === 'https://kernel.yaala.ai/docs/next/installation' ||
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
          content: 'Open Agent Kernel (OAK) is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, or Google ADK to AWS, Azure, or GCP. Built-in messaging integrations, session and memory management, knowledge bases, testing framework, guardrails, and observability.',
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
          alt: 'Open Agent Kernel logo',
          src: 'img/branding/open-agent-kernel-color.svg',
          srcDark: 'img/branding/open-agent-kernel-white-orange.svg',
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
          {
            to: '/docs/quick-start',
            label: 'Quick start',
            position: 'right',
            className: 'ak-btn ak-btn--primary ak-btn--small navbar-cta',
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
        additionalLanguages: ['python', 'bash', 'json', 'yaml', 'hcl'],
      },
      colorMode: {
        // Light is the default. Visitors can switch to the dark mode from the navbar, and the choice is remembered.
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: false,
      },
      mermaid: {
        // Both entries use the customised base theme. The variables below are the dark palette;
        // on the light page src/theme/Mermaid sends the light palette with each diagram.
        theme: { light: 'base', dark: 'base' },
        options: {
          fontFamily: 'Archivo, sans-serif',
          fontSize: 15,
          // ELK gives compact, orthogonal edge routing on graph/flowchart
          // diagrams. Registered at module scope of src/theme/Mermaid/index.tsx
          // (keeping elkjs out of the main bundle); mermaid falls back to dagre
          // if it is ever unavailable.
          layout: 'elk',
          elk: { nodePlacementStrategy: 'NETWORK_SIMPLEX' },
          flowchart: { curve: 'basis' },
          sequence: { mirrorActors: false },
          themeVariables: {
            darkMode: true,
            background: '#011428',
            fontFamily: 'Archivo, sans-serif',
            fontSize: '15px',
            // nodes
            primaryColor: '#02284F',
            primaryTextColor: '#EAF3F8',
            primaryBorderColor: '#3F598A',
            // edges + labels
            lineColor: '#ABCEE1',
            edgeLabelBackground: '#011C37',
            // subgraphs / clusters
            clusterBkg: '#011C37',
            clusterBorder: '#173964',
            titleColor: '#B1CDFF',
            // secondary/tertiary (misc fills)
            secondaryColor: '#0D315A',
            tertiaryColor: '#011C37',
            tertiaryTextColor: '#EAF3F8',
            // sequence diagrams
            actorBkg: '#02284F',
            actorBorder: '#3F598A',
            actorTextColor: '#EAF3F8',
            actorLineColor: '#3F598A',
            signalColor: '#ABCEE1',
            signalTextColor: '#EAF3F8',
            labelBoxBkgColor: '#0D315A',
            labelBoxBorderColor: '#3F598A',
            labelTextColor: '#EAF3F8',
            loopTextColor: '#B1CDFF',
            noteBkgColor: '#0D315A',
            noteBorderColor: '#173964',
            noteTextColor: '#EAF3F8',
            activationBkgColor: '#0D315A',
            activationBorderColor: '#3F598A',
            sequenceNumberColor: '#011428',
          },
        },
      }
    }),
};

export default config;
