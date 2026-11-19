import React, {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import clsx from 'clsx';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {
  PageMetadata,
  HtmlClassNameProvider,
  ThemeClassNames,
} from '@docusaurus/theme-common';
import {useHistory, useLocation} from '@docusaurus/router';
import Layout from '@theme/Layout';
import SearchMetadata from '@theme/SearchMetadata';
import BlogListPageStructuredData from '@theme/BlogListPage/StructuredData';
import type {Props} from '@theme/BlogListPage';
import PageHero from '@site/src/components/ui/PageHero';
import BlogPostCard from '@site/src/components/Blog/BlogPostCard';
import {
  BLOG_TOPICS,
  postMatchesTopic,
} from '@site/src/components/Blog/topics';
import styles from './styles.module.css';

function BlogListPageMetadata(props: Props): ReactNode {
  const {metadata} = props;
  const {
    siteConfig: {title: siteTitle},
  } = useDocusaurusContext();
  const {blogDescription, blogTitle, permalink} = metadata;
  const isBlogOnlyMode = permalink === '/';
  const title = isBlogOnlyMode ? siteTitle : blogTitle;
  return (
    <>
      <PageMetadata title={title} description={blogDescription} />
      <SearchMetadata tag="blog_posts_list" />
    </>
  );
}

/**
 * The blog index, in the site's page pattern: the shared page header, a topic filter that
 * stays in view, the newest post as a lead card, and the rest as a grid of cards.
 */
function BlogListPageContent(props: Props): ReactNode {
  const {items} = props;
  const history = useHistory();
  const location = useLocation();
  const [activeTopicSlug, setActiveTopicSlug] = useState<string | null>(null);

  // The filter state lives in the URL (?topic=...) so filtered views are
  // shareable. It is applied after mount to keep hydration consistent with
  // the statically rendered (unfiltered) page.
  useEffect(() => {
    setActiveTopicSlug(new URLSearchParams(location.search).get('topic'));
  }, [location.search]);

  const availableTopics = useMemo(
    () =>
      BLOG_TOPICS.filter((topic) =>
        items.some((item) =>
          postMatchesTopic(item.content.metadata.tags, topic),
        ),
      ),
    [items],
  );

  const activeTopic =
    availableTopics.find((topic) => topic.slug === activeTopicSlug) ?? null;

  const visibleItems = activeTopic
    ? items.filter((item) =>
        postMatchesTopic(item.content.metadata.tags, activeTopic),
      )
    : items;

  // With no filter, the newest post leads the page. A filtered view is a plain grid.
  const lead = activeTopic ? null : visibleItems[0];
  const rest = lead ? visibleItems.slice(1) : visibleItems;

  const selectTopic = (slug: string | null) => {
    history.push({search: slug ? `?topic=${slug}` : ''});
  };

  return (
    <Layout>
      <PageHero
        label="Blog"
        title="What we ship, and how it works"
        lead="Product announcements, engineering deep dives and stories from the OAK team."
      />
      <main className={clsx('ak-container', styles.page)}>
        <nav className={styles.topicBar} aria-label="Filter posts by topic">
          <button
            type="button"
            className={clsx(styles.topic, !activeTopic && styles.topicActive)}
            aria-pressed={!activeTopic}
            onClick={() => selectTopic(null)}>
            All
          </button>
          {availableTopics.map((topic) => (
            <button
              key={topic.slug}
              type="button"
              className={clsx(
                styles.topic,
                activeTopic?.slug === topic.slug && styles.topicActive,
              )}
              aria-pressed={activeTopic?.slug === topic.slug}
              onClick={() => selectTopic(topic.slug)}>
              {topic.label}
            </button>
          ))}
        </nav>

        {lead && (
          <div className={styles.lead}>
            <BlogPostCard content={lead.content} lead />
          </div>
        )}
        <section className={styles.grid} aria-label="Posts">
          {rest.map(({content}) => (
            <BlogPostCard key={content.metadata.permalink} content={content} />
          ))}
        </section>
        {visibleItems.length === 0 && (
          <p className={clsx('ak-body', styles.empty)}>
            No posts in this topic yet.
          </p>
        )}
      </main>
    </Layout>
  );
}

export default function BlogListPage(props: Props): ReactNode {
  return (
    <HtmlClassNameProvider
      className={clsx(
        ThemeClassNames.wrapper.blogPages,
        ThemeClassNames.page.blogListPage,
      )}>
      <BlogListPageMetadata {...props} />
      <BlogListPageStructuredData {...props} />
      <BlogListPageContent {...props} />
    </HtmlClassNameProvider>
  );
}
