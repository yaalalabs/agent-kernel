import React, { type ReactNode } from 'react';

type SectionHeaderProps = {
  /** Two-digit section number, shown in the accent colour. Omit for an unnumbered label. */
  index?: string;
  /** Short uppercase label above the heading. */
  label: string;
  title: ReactNode;
  /** One line under the heading. */
  lead?: ReactNode;
  /** Heading level. Every page has one `h1`; sections use `h2`. */
  as?: 'h1' | 'h2';
  id?: string;
};

/**
 * The one section-header pattern for the site: a numbered monospace label, a heading and a lead,
 * left aligned. Styles live in custom.css with the rest of the design system.
 */
export default function SectionHeader({ index, label, title, lead, as = 'h2', id }: SectionHeaderProps): JSX.Element {
  const Heading = as;
  return (
    <header className="ak-section-header">
      <p className="ak-label">
        {index && <span className="ak-label__index">{index}</span>}
        {label}
      </p>
      <Heading id={id} className={as === 'h1' ? 'ak-h1' : 'ak-h2'}>
        {title}
      </Heading>
      {lead && <p className="ak-lead">{lead}</p>}
    </header>
  );
}
