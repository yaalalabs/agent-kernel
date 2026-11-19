import React, {type ReactNode} from 'react';
import clsx from 'clsx';
import {
  PageMetadata,
  HtmlClassNameProvider,
  ThemeClassNames,
} from '@docusaurus/theme-common';
import {useBlogTagsPostsPageTitle} from '@docusaurus/theme-common/internal';
import Layout from '@theme/Layout';
import SearchMetadata from '@theme/SearchMetadata';
import Unlisted from '@theme/ContentVisibility/Unlisted';
import type {Props} from '@theme/BlogTagsPostsPage';
import PageHero from '@site/src/components/ui/PageHero';
import BlogPostCard from '@site/src/components/Blog/BlogPostCard';
import styles from './styles.module.css';

function BlogTagsPostsPageMetadata({tag}: Props): ReactNode {
  const title = useBlogTagsPostsPageTitle(tag);
  return (
    <>
      <PageMetadata title={title} description={tag.description} />
      <SearchMetadata tag="blog_tags_posts" />
    </>
  );
}

/** The posts under one tag, as the same grid of cards the blog index uses. */
function BlogTagsPostsPageContent({tag, items}: Props): ReactNode {
  const title = useBlogTagsPostsPageTitle(tag);
  return (
    <Layout>
      <PageHero
        back={{to: '/blog', label: 'All posts'}}
        label="Tag"
        title={title}
        lead={tag.description}
      />
      <main className={clsx('ak-container', styles.page)}>
        {tag.unlisted && <Unlisted />}
        <section className={styles.grid} aria-label="Posts">
          {items.map(({content}) => (
            <BlogPostCard key={content.metadata.permalink} content={content} />
          ))}
        </section>
      </main>
    </Layout>
  );
}

export default function BlogTagsPostsPage(props: Props): ReactNode {
  return (
    <HtmlClassNameProvider
      className={clsx(
        ThemeClassNames.wrapper.blogPages,
        ThemeClassNames.page.blogTagPostListPage,
      )}>
      <BlogTagsPostsPageMetadata {...props} />
      <BlogTagsPostsPageContent {...props} />
    </HtmlClassNameProvider>
  );
}
