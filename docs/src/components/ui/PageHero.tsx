import React, { type ReactNode } from 'react';
import Link from '@docusaurus/Link';
import clsx from 'clsx';

type PageHeroProps = {
  /** Short uppercase label above the title, for example "Features". */
  label: string;
  /** The page title. It renders as the page's one `h1`. */
  title: ReactNode;
  /** One or two sentences under the title. */
  lead?: ReactNode;
  /** Buttons or links under the lead: at most one primary action. */
  actions?: ReactNode;
  /** A drawing for the right-hand side. It is decorative and hidden from assistive technology. */
  art?: ReactNode;
  /** A way back to the page the visitor came from, shown above the label. */
  back?: { to: string; label: string };
};

/**
 * The header of every page below the home page: a label, the title, a lead, actions and an
 * optional drawing. Left aligned, flat, no background effect. Styles live in custom.css with
 * the rest of the design system.
 */
export default function PageHero({ label, title, lead, actions, art, back }: PageHeroProps): JSX.Element {
  return (
    <header className={clsx('ak-page-hero', art && 'ak-page-hero--with-art')}>
      <div className="ak-container ak-page-hero__inner">
        <div className="ak-page-hero__copy">
          {back && (
            <Link to={back.to} className="ak-page-hero__back">
              {back.label}
            </Link>
          )}
          <p className="ak-label">{label}</p>
          <h1 className="ak-h1">{title}</h1>
          {lead && <p className="ak-lead">{lead}</p>}
          {actions && <div className="ak-page-hero__actions">{actions}</div>}
        </div>
        {art && (
          <div className="ak-page-hero__art" aria-hidden="true">
            {art}
          </div>
        )}
      </div>
    </header>
  );
}
