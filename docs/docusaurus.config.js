// @ts-check
// `@type` JSDoc annotations allow editor autocompletion and type checking
// (when paired with `@ts-check`).
// There are various equivalent ways to declare your Docusaurus config.
// See: https://docusaurus.io/docs/api/docusaurus-config

import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Agent Kernel',
  tagline: 'Framework-agnostic runtime for AI agents',
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
        content: 'agent kernel, AI agents, AI framework, agentic AI, Yaala, Yaala Labs, LangGraph, OpenAI, agent runtime, agent deployment, AI infrastructure, machine learning, artificial intelligence, agent orchestration, multi-agent systems, agent-to-agent communication, Python AI framework, AI DevOps, MLOps, agent monitoring, stateful agents, serverless agents',
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
        content: 'Agent Kernel - Production-Ready AI Agent Runtime by Yaala Labs',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        property: 'og:description',
        content: 'Deploy and manage AI agents at scale with Agent Kernel. Framework-agnostic runtime supporting LangGraph, OpenAI Agents SDK and Google ADK. Built by Yaala Labs for enterprise AI infrastructure.',
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
        content: 'Agent Kernel - Production-Ready AI Agent Runtime by Yaala Labs',
      },
    },
    {
      tagName: 'meta',
      attributes: {
        name: 'twitter:description',
        content: 'Deploy and manage AI agents at scale with Agent Kernel. Framework-agnostic runtime supporting LangGraph, OpenAI Agents SDK and Google ADK. Built by Yaala Labs.',
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
        docsRouteBasePath: '/',
      },
    ],
  ],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl:
            'https://github.com/yaalalabs/agent-kernel/tree/develop/docs/',
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
          content: 'Agent Kernel by Yaala Labs is a production-ready, framework-agnostic runtime for deploying and managing AI agents. Supports LangGraph, OpenAI Agents, and custom frameworks with built-in state management, monitoring, and scalability.',
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
          {
            type: 'docSidebar',
            sidebarId: 'tutorialSidebar',
            position: 'left',
            label: 'Documentation',
          },
          {to: '/blog', label: 'Blog', position: 'left'},
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
                to: '/',
              },
              {
                label: 'Architecture',
                to: '/architecture/overview',
              },
              {
                label: 'API Reference',
                to: '/api/rest-api',
              },
            ],
          },
          {
            title: 'Community',
            items: [
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
    }),
};

export default config;
