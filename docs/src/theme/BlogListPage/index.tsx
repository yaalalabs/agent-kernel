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
import BlogLayout from '@theme/BlogLayout';
import BlogListPaginator from '@theme/BlogListPaginator';
import SearchMetadata from '@theme/SearchMetadata';
import BlogListPageStructuredData from '@theme/BlogListPage/StructuredData';
import type {Props} from '@theme/BlogListPage';
import BlogPostRow from '@site/src/components/Blog/BlogPostRow';
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

function BlogListPageContent(props: Props): ReactNode {
  const {metadata, items, sidebar} = props;
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

  const selectTopic = (slug: string | null) => {
    history.push({search: slug ? `?topic=${slug}` : ''});
  };

  return (
    <BlogLayout sidebar={sidebar}>
      <div className={styles.container}>
        <header className={styles.hero}>
          <h1 className={styles.heroTitle}>Blog</h1>
          <p className={styles.heroSubtitle}>
            Product announcements, engineering deep dives, and stories from
            the Agent Kernel team.
          </p>
        </header>
        <nav className={styles.topicBar} aria-label="Filter posts by topic">
          <button
            type="button"
            className={clsx(
              styles.topic,
              !activeTopic && styles.topicActive,
            )}
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
              onClick={() => selectTopic(topic.slug)}>
              {topic.label}
            </button>
          ))}
        </nav>
        <section className={styles.postList}>
          {visibleItems.map(({content}) => (
            <BlogPostRow key={content.metadata.permalink} content={content} />
          ))}
          {visibleItems.length === 0 && (
            <p className={styles.empty}>No posts in this topic yet.</p>
          )}
        </section>
        <BlogListPaginator metadata={metadata} />
      </div>
    </BlogLayout>
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
