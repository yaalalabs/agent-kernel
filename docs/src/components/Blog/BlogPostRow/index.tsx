import React, {type ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import type {Props as BlogPostItemsProps} from '@theme/BlogPostItems';
import {topicsForPost} from '@site/src/components/Blog/topics';
import styles from './styles.module.css';

type PostContent = BlogPostItemsProps['items'][number]['content'];

function formatDate(isoDate: string): string {
  // Filename-derived post dates are UTC midnight; format in UTC so viewers
  // west of UTC don't see the previous day (and SSR/client output matches).
  return new Date(isoDate).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

export default function BlogPostRow({
  content,
}: {
  content: PostContent;
}): ReactNode {
  const {metadata, frontMatter, assets} = content;
  const {permalink, title, description, date, readingTime, tags, authors} =
    metadata;
  const author = authors[0];
  const image = assets.image ?? (frontMatter.image as string | undefined);
  const imageUrl = useBaseUrl(image ?? '');
  const primaryTopic = topicsForPost(tags)[0];

  return (
    <article className={styles.row}>
      <div className={styles.body}>
        <div className={styles.meta}>
          {author?.imageURL && (
            <img
              className={styles.avatar}
              src={author.imageURL}
              alt=""
              loading="lazy"
            />
          )}
          {author?.name && (
            <>
              <span className={styles.author}>{author.name}</span>
              <span className={styles.dot} aria-hidden="true">
                ·
              </span>
            </>
          )}
          <time dateTime={date}>{formatDate(date)}</time>
        </div>
        <Link to={permalink} className={styles.titleLink}>
          <h2 className={styles.title}>{title}</h2>
          {description && <p className={styles.excerpt}>{description}</p>}
        </Link>
        <div className={styles.footerRow}>
          {readingTime !== undefined && (
            <span className={styles.readTime}>
              {Math.ceil(readingTime)} min read
            </span>
          )}
          {primaryTopic && (
            <Link
              to={`/blog?topic=${primaryTopic.slug}`}
              className={styles.topicChip}>
              {primaryTopic.label}
            </Link>
          )}
        </div>
      </div>
      {image && (
        <Link
          to={permalink}
          className={styles.thumbLink}
          tabIndex={-1}
          aria-hidden="true">
          <img
            className={styles.thumb}
            src={imageUrl}
            alt=""
            loading="lazy"
          />
        </Link>
      )}
    </article>
  );
}
