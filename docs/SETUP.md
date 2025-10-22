# Agent Kernel Documentation - Setup Guide

This guide will help you set up and deploy the Agent Kernel documentation to GitHub Pages.

## 📋 Overview

A comprehensive Docusaurus 3 documentation site.

### GitHub Actions Workflow
```
.github/
└── workflows/
    └── deploy-docs.yml                  # Auto-deploy to GitHub Pages
```

## 🚀 Getting Started

### 1. Install Dependencies

```bash
cd docs
npm install
```

### 2. Run Locally

```bash
npm start
```

This will open `http://localhost:3000` in your browser.

### 3. Build for Production

```bash
npm run build
```

### 4. Test Production Build

```bash
npm run serve
```

## 🌐 GitHub Pages Deployment

### Automatic Deployment

The documentation will automatically deploy when you:
- Push to `develop` branch
- Make changes in the `docs/` directory

The workflow is configured in `.github/workflows/deploy-docs.yml`

### Access Your Documentation

After deployment (takes ~2-5 minutes), website will be available at:

```
https://kernel.yaala.ai/
```

## 🎨 Customization


### Add a New Page

1. Create `docs/docs/your-page.md`:

```markdown
---
sidebar_position: 1
---

# Your Page Title

Your content here...
```

2. The page will automatically appear in the sidebar

### Add a Blog Post

1. Create `docs/blog/YYYY-MM-DD-title.md`:

```markdown
---
slug: /blog/your-post
title: Your Blog Post
authors: [yourname]
tags: [tag1, tag2]
---

# Your Blog Post

Introduction here...

<!-- truncate -->

Full content here...
```

### Add Mermaid Diagrams

```markdown
```mermaid
graph LR
    A[Start] --> B[Process]
    B --> C[End]
```
```

## 🔧 Configuration Details

### Mermaid Support

Mermaid diagrams are enabled in `docusaurus.config.js`:

```javascript
markdown: {
  mermaid: true,
},
themes: ['@docusaurus/theme-mermaid'],
```

### Code Highlighting

Supports Python, Bash, JSON, YAML, and more:

```javascript
prism: {
  theme: prismThemes.github,
  darkTheme: prismThemes.dracula,
  additionalLanguages: ['python', 'bash', 'json', 'yaml'],
},
```

## 📞 Support

If you need help:
- Review this guide
- Check Docusaurus documentation
- Open an issue on GitHub

---

**Happy Documenting! 📖**
