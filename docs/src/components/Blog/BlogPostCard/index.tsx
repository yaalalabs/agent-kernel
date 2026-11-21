import React, {type ReactNode} from 'react';
import clsx from 'clsx';
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

/**
 * One post on the blog index and on a tag page: its banner, a line of facts (topic, date,
 * reading time), the title, the description and the author. `lead` is the wide form used for
 * the newest post, with the banner beside the text.
 */
export default function BlogPostCard({
  content,
  lead = false,
}: {
  content: PostContent;
  lead?: boolean;
}): ReactNode {
  const {metadata, frontMatter, assets} = content;
  const {permalink, title, description, date, readingTime, tags, authors} =
    metadata;
  const author = authors[0];
  const image = assets.image ?? (frontMatter.image as string | undefined);
  const imageUrl = useBaseUrl(image ?? '');
  const topic = topicsForPost(tags)[0];

  return (
    <article className={clsx(styles.card, lead && styles.lead)}>
      {image && (
        <Link
          to={permalink}
          className={styles.banner}
          tabIndex={-1}
          aria-hidden="true">
          <img src={imageUrl} alt="" loading={lead ? 'eager' : 'lazy'} />
        </Link>
      )}
      <div className={styles.body}>
        <p className={clsx('ak-label', styles.facts)}>
          {topic && (
            <Link to={`/blog?topic=${topic.slug}`} className={styles.topic}>
              {topic.label}
            </Link>
          )}
          <time dateTime={date}>{formatDate(date)}</time>
          {/* The reading time is kept for the lead card: a grid card's line has room for two facts */}
          {lead && readingTime !== undefined && (
            <span>{Math.ceil(readingTime)} min read</span>
          )}
        </p>
        <h2 className={clsx(lead ? 'ak-h3' : 'ak-h4', styles.title)}>
          <Link to={permalink}>{title}</Link>
        </h2>
        {description && (
          <p className={clsx(lead ? 'ak-body' : 'ak-small', styles.excerpt)}>
            {description}
          </p>
        )}
        {author?.name && (
          <p className={styles.author}>
            {author.imageURL && (
              <img src={author.imageURL} alt="" loading="lazy" />
            )}
            {author.name}
          </p>
        )}
      </div>
    </article>
  );
}
