import React, {type ReactNode} from 'react';
import clsx from 'clsx';
import {HtmlClassNameProvider, ThemeClassNames} from '@docusaurus/theme-common';
import {
  BlogPostProvider,
  useBlogPost,
} from '@docusaurus/plugin-content-blog/client';
import Layout from '@theme/Layout';
import BlogPostItem from '@theme/BlogPostItem';
import BlogPostPaginator from '@theme/BlogPostPaginator';
import BlogPostPageMetadata from '@theme/BlogPostPage/Metadata';
import BlogPostPageStructuredData from '@theme/BlogPostPage/StructuredData';
import ContentVisibility from '@theme/ContentVisibility';
import TOC from '@theme/TOC';
import type BlogPostPageType from '@theme/BlogPostPage';
import type {WrapperProps} from '@docusaurus/types';
import Link from '@docusaurus/Link';
import {topicsForPost} from '@site/src/components/Blog/topics';

type Props = WrapperProps<typeof BlogPostPageType>;

/**
 * A blog post in the site's page pattern: a reading column at the prose measure on the page
 * container, with the way back and the post's topic above the title, and a table of contents
 * beside it on a wide screen. The styles are in src/css/blog.css.
 */
function BlogPostPageContent({children}: {children: ReactNode}): ReactNode {
  const {metadata, toc, frontMatter} = useBlogPost();
  const {nextItem, prevItem, tags} = metadata;
  const topic = topicsForPost(tags)[0];
  const showContents = !frontMatter.hide_table_of_contents && toc.length > 0;

  return (
    <Layout>
      <ContentVisibility metadata={metadata} />
      <div className={clsx('ak-container', 'blog-post')}>
        <main className="blog-post__column">
          <Link to="/blog" className="ak-page-hero__back">
            All posts
          </Link>
          {topic && (
            <p className="ak-label blog-post__topic">
              <Link to={`/blog?topic=${topic.slug}`}>{topic.label}</Link>
            </p>
          )}
          <BlogPostItem>{children}</BlogPostItem>
          {(nextItem || prevItem) && (
            <BlogPostPaginator nextItem={nextItem} prevItem={prevItem} />
          )}
        </main>
        {showContents && (
          <aside className="blog-post__contents" aria-label="On this page">
            <p className="ak-label">On this page</p>
            <TOC
              toc={toc}
              minHeadingLevel={frontMatter.toc_min_heading_level}
              maxHeadingLevel={frontMatter.toc_max_heading_level}
            />
          </aside>
        )}
      </div>
    </Layout>
  );
}

export default function BlogPostPageWrapper(props: Props): ReactNode {
  const BlogPostContent = props.content;
  return (
    <BlogPostProvider content={props.content} isBlogPostPage>
      <HtmlClassNameProvider
        className={clsx(
          ThemeClassNames.wrapper.blogPages,
          ThemeClassNames.page.blogPostPage,
        )}>
        <BlogPostPageMetadata />
        <BlogPostPageStructuredData />
        <BlogPostPageContent>
          <BlogPostContent />
        </BlogPostPageContent>
      </HtmlClassNameProvider>
    </BlogPostProvider>
  );
}
