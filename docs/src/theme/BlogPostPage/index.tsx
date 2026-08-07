import React, {type ReactNode} from 'react';
import clsx from 'clsx';
import {HtmlClassNameProvider, ThemeClassNames} from '@docusaurus/theme-common';
import {
  BlogPostProvider,
  useBlogPost,
} from '@docusaurus/plugin-content-blog/client';
import BlogLayout from '@theme/BlogLayout';
import BlogPostItem from '@theme/BlogPostItem';
import BlogPostPaginator from '@theme/BlogPostPaginator';
import BlogPostPageMetadata from '@theme/BlogPostPage/Metadata';
import BlogPostPageStructuredData from '@theme/BlogPostPage/StructuredData';
import ContentVisibility from '@theme/ContentVisibility';
import type BlogPostPageType from '@theme/BlogPostPage';
import type {WrapperProps} from '@docusaurus/types';
import type {BlogSidebar} from '@docusaurus/plugin-content-blog';
import Link from '@docusaurus/Link';

type Props = WrapperProps<typeof BlogPostPageType>;

const ArrowLeftIcon = () => (
  <svg
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="14 18 8 12 14 6" />
  </svg>
);

function BlogPostPageContent({
  sidebar,
  children,
}: {
  sidebar: BlogSidebar;
  children: ReactNode;
}): ReactNode {
  const {metadata} = useBlogPost();
  const {nextItem, prevItem} = metadata;
  return (
    <BlogLayout sidebar={sidebar}>
      <ContentVisibility metadata={metadata} />

      <div className="blog-post-medium-column">
        <div className="blog-back-btn-container">
          <Link to="/blog" className="blog-back-btn" title="Back to Blog" aria-label="Back to Blog">
            <ArrowLeftIcon />
          </Link>
        </div>
        <BlogPostItem>{children}</BlogPostItem>

        {(nextItem || prevItem) && (
          <BlogPostPaginator nextItem={nextItem} prevItem={prevItem} />
        )}
      </div>
    </BlogLayout>
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
        <BlogPostPageContent sidebar={props.sidebar}>
          <BlogPostContent />
        </BlogPostPageContent>
      </HtmlClassNameProvider>
    </BlogPostProvider>
  );
}
