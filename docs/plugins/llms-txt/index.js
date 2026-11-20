// @ts-check
/**
 * Writes /llms.txt and /llms-full.txt at build time (https://llmstxt.org).
 *
 * - llms.txt is an index for AI assistants: the hand-written summary in `template.md`, then every
 *   page of the released docs in sidebar order, each with its link and opening sentence, then the
 *   blog posts.
 * - llms-full.txt is the text of those docs pages in one file, in the same order, with every
 *   link made absolute so that it still works outside the page it came from.
 *
 * Both are built from what Docusaurus has already loaded (titles, permalinks and the resolved
 * sidebar) and from the pages' own markdown, so they follow the docs without anyone editing a
 * list. They describe the released docs, the ones served at /docs, because that is what an
 * installed package matches. The files exist only in a build: `npm start` does not serve them.
 */

const fs = require('node:fs/promises');
const path = require('node:path');
const { oneSentence, bodyOf, openingOf, rewriteLinks } = require('./text');

const DOCS_PLUGIN = 'docusaurus-plugin-content-docs';
const BLOG_PLUGIN = 'docusaurus-plugin-content-blog';

/**
 * The sidebar as sections: the loose pages at the top level first, then one section per
 * top-level category. A nested category is flattened into its parent's section, and its pages
 * remember its label (`group`), so that a page titled "Overview" can say what it is an overview of.
 */
function sectionsOf(sidebar, firstTitle) {
  const sections = [{ title: firstTitle, pages: [] }];
  const collect = (items, into, group) => {
    for (const item of items) {
      if (item.type === 'doc' || item.type === 'ref') into.push({ id: item.id, group });
      if (item.type === 'category') {
        if (item.link?.type === 'doc') into.push({ id: item.link.id, group: item.label });
        collect(item.items, into, item.label);
      }
    }
  };
  for (const item of sidebar) {
    if (item.type === 'category') {
      const section = { title: item.label, pages: [] };
      if (item.link?.type === 'doc') section.pages.push({ id: item.link.id, group: undefined });
      collect(item.items, section.pages, undefined);
      sections.push(section);
    } else if (item.type === 'doc' || item.type === 'ref') {
      sections[0].pages.push({ id: item.id, group: undefined });
    }
  }
  return sections.filter((section) => section.pages.length > 0);
}

/** @returns {import('@docusaurus/types').Plugin} */
module.exports = function llmsTxtPlugin(context) {
  return {
    name: 'oak-llms-txt',

    async postBuild({ outDir, plugins, siteConfig }) {
      const site = siteConfig.url.replace(/\/$/, '');
      // A page's address as the site serves it: with `trailingSlash: false` the docs home is
      // /docs, though its permalink is recorded as /docs/.
      const absolute = (permalink) =>
        `${site}${siteConfig.trailingSlash === false && permalink.length > 1 ? permalink.replace(/\/$/, '') : permalink}`;

      const docsPlugin = plugins.find((plugin) => plugin.name === DOCS_PLUGIN);
      const versions = /** @type {any} */ (docsPlugin?.content)?.loadedVersions ?? [];
      // The version served at /docs: the last release, or the working docs before any release.
      const version = versions.find((candidate) => candidate.isLast) ?? versions[0];
      if (!version) {
        throw new Error('llms-txt: the docs plugin has no loaded version to describe.');
      }

      // Every published page, with its markdown read once for both files.
      const published = version.docs.filter((doc) => !doc.draft && !doc.unlisted);
      const byId = new Map();
      const bySource = new Map();
      for (const doc of published) {
        const file = doc.source.replace(/^@site/, context.siteDir);
        const page = { doc, file, body: bodyOf(await fs.readFile(file, 'utf8')) };
        byId.set(doc.id, page);
        bySource.set(path.normalize(file), page);
      }

      const sidebar = Object.values(version.sidebars)[0] ?? [];
      const sections = sectionsOf(sidebar, 'Getting started');
      // A page that no sidebar lists is still part of the docs.
      const listed = new Set(sections.flatMap((section) => section.pages.map((page) => page.id)));
      const loose = published.filter((doc) => !listed.has(doc.id));
      if (loose.length > 0) {
        sections.push({ title: 'More', pages: loose.map((doc) => ({ id: doc.id, group: undefined })) });
      }

      const entry = (title, permalink, description) =>
        `- [${title}](${absolute(permalink)})${description ? `: ${description}` : ''}`;

      const docsIndex = sections
        .map((section) => {
          const lines = [];
          for (const { id, group } of section.pages) {
            const page = byId.get(id);
            if (!page) continue;
            const { doc, body } = page;
            // "Overview" alone says nothing in a flat list: name what it is an overview of.
            const title = group && /^overview$/i.test(doc.title) ? `${group} overview` : doc.title;
            const description = oneSentence(doc.frontMatter?.description || openingOf(body) || doc.description);
            lines.push(entry(title, doc.permalink, description));
          }
          return `## ${section.title}\n\n${lines.join('\n')}`;
        })
        .join('\n\n');

      // A post is described the way a docs page is: by its front matter, else by its opening
      // paragraph. Docusaurus' own excerpt is the first line of the post, which is the banner
      // image under the title, so it would give the banner's alt text.
      const blogPlugin = plugins.find((plugin) => plugin.name === BLOG_PLUGIN);
      const posts = /** @type {any} */ (blogPlugin?.content)?.blogPosts ?? [];
      const blogLines = [];
      for (const { metadata } of posts) {
        if (metadata.draft || metadata.unlisted) continue;
        const text = await fs.readFile(metadata.source.replace(/^@site/, context.siteDir), 'utf8');
        const description = oneSentence(
          metadata.frontMatter?.description || openingOf(bodyOf(text)) || metadata.description,
        );
        blogLines.push(entry(metadata.title, metadata.permalink, description));
      }
      const blogIndex = blogLines.join('\n');

      const template = await fs.readFile(path.join(__dirname, 'template.md'), 'utf8');
      // Function replacers: a string replacement would read "$&" or "$'" in the text as a pattern.
      const index = template
        .replaceAll('{{site}}', () => site)
        .replaceAll('{{version}}', () => version.versionName)
        .replaceAll('{{docs}}', () => docsIndex)
        .replaceAll('{{blog}}', () => blogIndex);
      await fs.writeFile(path.join(outDir, 'llms.txt'), `${index.trim()}\n`);

      // The full text: every listed page, in the same order, under a line that says where it lives.
      // In one long file a relative link points nowhere, so every link is made absolute: a link to
      // a markdown file becomes the address of that page, and any other path is resolved from the
      // address of the page it is on.
      const fullText = [];
      for (const section of sections) {
        for (const { id } of section.pages) {
          const page = byId.get(id);
          if (!page) continue;
          const address = absolute(page.doc.permalink);
          const resolve = (target) => {
            const [pathname, hash = ''] = target.split('#');
            const anchor = hash ? `#${hash}` : '';
            if (/\.mdx?$/.test(pathname) && !pathname.startsWith('/')) {
              const linked = bySource.get(path.normalize(path.resolve(path.dirname(page.file), pathname)));
              if (linked) return `${absolute(linked.doc.permalink)}${anchor}`;
            }
            try {
              return new URL(target, address).href;
            } catch {
              return target;
            }
          };
          fullText.push(`Source: ${address}\n\n${rewriteLinks(page.body, resolve)}`);
        }
      }
      const head = [
        '# Open Agent Kernel documentation',
        '',
        `> The full text of the Open Agent Kernel (OAK) documentation for version ${version.versionName}, ` +
          `one page after another in the order of the docs sidebar. Each page starts with a "Source:" line ` +
          `giving its address. The index of these pages is at ${site}/llms.txt.`,
      ].join('\n');
      await fs.writeFile(path.join(outDir, 'llms-full.txt'), `${[head, ...fullText].join('\n\n---\n\n')}\n`);
    },
  };
};
