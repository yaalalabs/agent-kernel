// @ts-check
// `@type` JSDoc annotations allow editor autocompletion and type checking
// (when paired with `@ts-check`).
// There are various equivalent ways to declare your Docusaurus config.
// See: https://docusaurus.io/docs/api/docusaurus-config

import { themes as prismThemes } from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Agent Kernel',
  tagline: 'Production-ready framework-agnostic runtime for AI agents - Deploy agents built with your favorite framework enabling enterprise features',
  favicon: 'img/favicon.ico',
  url: 'https://kernel.yaala.ai',
  baseUrl: '/',

  // GitHub pages deployment config.
  organizationName: 'yaalalabs',
  projectName: 'agent-kernel',
  trailingSlash: false,

  onBrokenLinks: 'throw',

  // SEO head tags
  headTags: [
    {
      tagName: 'meta',
      attributes: {
        name: 'keywords',
        content: 'agent kernel, agentic framework, agentic frameworks, AI agent runtime, LangGraph runtime, OpenAI Agents deployment, Google ADK deployment, CrewAI deployment, agent kernel vs semantic kernel, production AI agents, AI agent orchestration, multi-agent systems, LangGraph production, OpenAI Agents SDK, Google Gemini ADK, framework-agnostic agents, agent deployment platform, stateful AI agents, AI agent monitoring, LangGraph alternative, OpenAI agent framework, Python AI agents, enterprise AI agents, AI DevOps, MLOps agents, agent-to-agent communication, serverless agents, containerized agents',
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
        content: 'Agent Kernel - Production Runtime for LangGraph, OpenAI, Google ADK & CrewAI | Agentic Framework',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:description',
        content: 'Agent Kernel: The production-ready agentic framework runtime. Deploy LangGraph, OpenAI Agents SDK, Google ADK (Gemini), and CrewAI with built-in state management, monitoring, and enterprise scalability. Framework-agnostic alternative to Semantic Kernel.',
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
        content: 'Agent Kernel - Production Runtime for LangGraph, OpenAI, Google ADK & CrewAI',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'twitter:description',
        content: 'Production agentic framework runtime for LangGraph, OpenAI Agents SDK, Google ADK, and CrewAI. Enterprise-ready alternative to Semantic Kernel with state management and monitoring.',
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
        content: 'AI Infrastructure, Machine Learning, Software Development',
      },
    },
    {
      tagName: 'link',
      attributes: {
        rel: 'canonical',
        href: 'https://kernel.yaala.ai',
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
        description: 'Production-ready agentic framework runtime for LangGraph, OpenAI Agents SDK, Google ADK, and CrewAI. Framework-agnostic runtime.',
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
        keywords: 'Agent kernel, agentic framework, LangGraph runtime, OpenAI Agents, Google ADK, CrewAI, AI agent deployment, agent kernel vs semantic kernel',
        featureList: [
          'LangGraph support',
          'OpenAI Agents SDK support',
          'Google ADK (Gemini) support',
          'CrewAI support',
          'Multi-agent orchestration',
          'State management',
          'Production monitoring',
          'Framework-agnostic runtime',
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
        description: 'Enterprise AI infrastructure and agentic framework solutions',
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
          ignorePatterns: ['/tags/**'],
          filename: 'sitemap.xml',
          createSitemapItems: async (params) => {
            const {defaultCreateSitemapItems, ...rest} = params;
            const items = await defaultCreateSitemapItems(rest);
            return items.map((item) => {
              // Set highest priority for key landing pages
              if (item.url === 'https://kernel.yaala.ai/' || 
                  item.url === 'https://kernel.yaala.ai/docs' ||
                  item.url === 'https://kernel.yaala.ai/docs/quick-start' ||
                  item.url === 'https://kernel.yaala.ai/docs/installation' ||
                  item.url === 'https://kernel.yaala.ai/features' ||
                  item.url === 'https://kernel.yaala.ai/blog') {
                return {...item, priority: 1.0, changefreq: 'daily'};
              }
              // High priority for blog posts
              if (item.url.includes('/blog/') && !item.url.includes('/blog/tags') && !item.url.includes('/blog/archive')) {
                return {...item, priority: 0.8, changefreq: 'weekly'};
              }
              // Medium priority for documentation pages
              if (item.url.includes('/docs/')) {
                return {...item, priority: 0.7, changefreq: 'weekly'};
              }
              // Lower priority for blog tags and archives
              if (item.url.includes('/blog/tags') || item.url.includes('/blog/archive') || item.url.includes('/blog/authors')) {
                return {...item, priority: 0.3};
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
          content: 'Agent Kernel: Production-ready agentic framework runtime for LangGraph, OpenAI Agents SDK, Google ADK (Gemini), and CrewAI. Deploy and scale AI agents with enterprise features. Framework-agnostic alternative to Semantic Kernel with built-in state management, monitoring, and observability.',
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
        title: 'Agent Kernel',
        logo: {
          alt: 'Agent Kernel Logo',
          src: 'img/logo.svg',
        },
        items: [
          { to: '/features', label: 'Explore Features', position: 'left' },
          {
            type: 'docSidebar',
            sidebarId: 'tutorialSidebar',
            position: 'left',
            label: 'Documentation',
          },
          { to: '/blog', label: 'Blog', position: 'left' }, 
          {
            type: 'docsVersionDropdown',
            position: 'right',
            dropdownActiveClassDisabled: true,
            dropdownItemsAfter: [],
          },
          {
            href: 'https://discord.gg/snrPzb46uu',
            position: 'right',
            className: 'header-discord-link',
            'aria-label': 'Discord Community',
          },
          {
            href: 'https://pypi.org/project/agentkernel/',
            position: 'right',
            className: 'header-pypi-link',
            'aria-label': 'PyPI package',
          },
          {
            href: 'https://registry.terraform.io/modules/yaalalabs',
            position: 'right',
            className: 'header-terraform-link',
            'aria-label': 'Terraform registry',
          },
          {
            href: 'https://github.com/yaalalabs/agent-kernel',
            position: 'right',
            className: 'header-github-link',
            'aria-label': 'GitHub repository',
          },
        ],
      },
      footer: {
        style: 'dark',
        logo: {
          alt: 'Yaala Labs Logo',
          src: 'img/yaala_white.png',
          href: 'https://www.yaalalabs.com/',
          width: 160,
        },
        links: [
          {
            title: 'Docs',
            items: [
              {
                label: 'Getting Started',
                to: '/docs',
              },
              {
                label: 'Architecture',
                to: '/docs/architecture/overview',
              },
              {
                label: 'API Reference',
                to: '/docs/api/rest-api',
              },
            ],
          },
          {
            title: 'Community',
            items: [
              {
                label: 'Discord',
                href: 'https://discord.gg/snrPzb46uu',
              },
              {
                label: 'GitHub',
                href: 'https://github.com/yaalalabs/agent-kernel',
              },
              {
                label: 'Issues',
                href: 'https://github.com/yaalalabs/agent-kernel/issues',
              },
            ],
          },
          {
            title: 'More',
            items: [
              {
                label: 'Blog',
                to: '/blog',
              },
              {
                label: 'PyPI',
                href: 'https://pypi.org/project/agentkernel/',
              },
              {
                label: 'Terraform',
                href: 'https://registry.terraform.io/modules/yaalalabs',
              },
            ],
          },
          {
            title: 'Legal',
            items: [
              {
                label: 'Privacy Policy',
                to: '/privacy-policy',
              },
              {
                label: 'Terms of Use',
                to: '/terms-of-use',
              },
              {
                label: 'Cookie Policy',
                to: '/cookie-policy',
              },
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} Yaala Labs`,
      },
      prism: {
        theme: prismThemes.oneLight,
        darkTheme: prismThemes.oneDark,
        additionalLanguages: ['python', 'bash', 'json', 'yaml'],
      },
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
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
