import React, {type ReactNode} from 'react';
import clsx from 'clsx';
import type {Props} from '@theme/Footer/Layout';
import {FaDiscord, FaGithub, FaXTwitter, FaEnvelope} from 'react-icons/fa6';
import {SiTerraform} from 'react-icons/si';

type SocialLink = {
  href: string;
  label: string;
  icon: ReactNode;
};

function PypiIcon(): ReactNode {
  return (
    <svg
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false">
      <path
        fill="currentColor"
        d="M14.25.18l.9.2.73.26.59.3.45.32.34.34.25.34.16.33.1.3.04.26.02.2-.01.13V8.5l-.05.63-.13.55-.21.46-.26.38-.3.31-.33.25-.35.19-.35.14-.33.1-.3.07-.26.04-.21.02H8.77l-.69.05-.59.14-.5.22-.41.27-.33.32-.27.35-.2.36-.15.37-.1.35-.07.32-.04.27-.02.21v3.06H3.17l-.21-.03-.28-.07-.32-.12-.35-.18-.36-.26-.36-.36-.35-.46-.32-.59-.28-.73-.21-.88-.14-1.05-.05-1.23.06-1.22.16-1.04.24-.87.32-.71.36-.57.4-.44.42-.33.42-.24.4-.16.36-.1.32-.05.24-.01h.16l.06.01h8.16v-.83H6.18l-.01-2.75-.02-.37.05-.34.11-.31.17-.28.25-.26.31-.23.38-.2.44-.18.51-.15.58-.12.64-.1.71-.06.77-.04.84-.02 1.27.05zm-6.3 1.98l-.23.33-.08.41.08.41.23.34.33.22.41.09.41-.09.33-.22.23-.34.08-.41-.08-.41-.23-.33-.33-.22-.41-.09-.41.09zm13.09 3.95l.28.06.32.12.35.18.36.27.36.35.35.47.32.59.28.73.21.88.14 1.04.05 1.23-.06 1.23-.16 1.04-.24.86-.32.71-.36.57-.4.45-.42.33-.42.24-.4.16-.36.09-.32.05-.24.02-.16-.01h-8.22v.82h5.84l.01 2.76.02.36-.05.34-.11.31-.17.29-.25.25-.31.24-.38.2-.44.17-.51.15-.58.13-.64.09-.71.07-.77.04-.84.01-1.27-.04-1.07-.14-.9-.2-.73-.25-.59-.3-.45-.33-.34-.34-.25-.34-.16-.33-.1-.3-.04-.25-.02-.2.01-.13v-5.34l.05-.64.13-.54.21-.46.26-.38.3-.32.33-.24.35-.2.35-.14.33-.1.3-.06.26-.04.21-.02.13-.01h5.84l.69-.05.59-.14.5-.21.41-.28.33-.32.27-.35.2-.36.15-.36.1-.35.07-.32.04-.28.02-.21V6.07h2.09l.14.01zm-6.47 14.25l-.23.33-.08.41.08.41.23.33.33.23.41.08.41-.08.33-.23.23-.33.08-.41-.08-.41-.23-.33-.33-.23-.41-.08-.41.08z"
      />
    </svg>
  );
}

const SOCIAL_LINKS: SocialLink[] = [
  {
    href: 'https://x.com/yaalalabs',
    label: 'X (Twitter)',
    icon: <FaXTwitter aria-hidden="true" />,
  },
  {
    href: 'https://pypi.org/project/agentkernel/',
    label: 'PyPI package',
    icon: <PypiIcon />,
  },
  {
    href: 'https://discord.gg/snrPzb46uu',
    label: 'Discord Community',
    icon: <FaDiscord aria-hidden="true" />,
  },
  {
    href: 'mailto:hello@yaalalabs.com',
    label: 'Email',
    icon: <FaEnvelope aria-hidden="true" />,
  },
];

export default function FooterLayout({
  style,
  links,
  logo,
  copyright,
}: Props): ReactNode {
  return (
    <footer
      className={clsx('footer', {
        'footer--dark': style === 'dark',
      })}>
      <div className="footer__inner">
        <div className="footer__top">
          {/* Left brand column */}
          <div className="footer__brand">
            <a href="/" className="footer__brand-logo-link" aria-label="Agent Kernel home">
              <img
                src="/img/branding/agent-kernel-icon-horizontal-color-dark-bg.svg"
                alt="Agent Kernel"
                className="footer__brand-logo"
                width={140}
              />
            </a>
            <p className="footer__brand-tagline">
              The open-source runtime and orchestration layer for scalable, compliant enterprise AI agents.
            </p>
            <ul className="footer__social-links" aria-label="Social media">
              {SOCIAL_LINKS.map((link) => (
                <li key={link.label}>
                  <a
                    href={link.href}
                    className="footer__social-link"
                    target={link.href.startsWith('mailto') ? undefined : '_blank'}
                    rel="noopener noreferrer"
                    aria-label={link.label}>
                    <span className="footer__social-icon" aria-hidden="true">
                      {link.icon}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
            <div className="footer__member-of">
              <span className="footer__member-label">Member of</span>
              <div className="footer__member-badges">
                <a
                  href="https://www.linuxfoundation.org"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="footer__badge-link">
                  <img
                    src="/img/lf_membership.svg"
                    alt="Linux Foundation Member"
                    className="footer__badge"
                  />
                </a>
                <a
                  href="https://aaif.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="footer__badge-link">
                  <img
                    src="/img/aaif_membership.svg"
                    alt="Agentic AI Foundation Member"
                    className="footer__badge"
                  />
                </a>
              </div>
            </div>
          </div>

          {/* Link columns */}
          <div className="footer__links-grid">
            {links}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="footer__bottom">
          <div className="footer__copyright">
            {copyright}
          </div>
          <div className="footer__legal-links">
            <a href="/privacy-policy" className="footer__legal-link">Privacy Policy</a>
            <a href="/terms-of-use" className="footer__legal-link">Terms of Use</a>
            <a href="/cookie-policy" className="footer__legal-link">Cookie Policy</a>
          </div>
        </div>
      </div>
    </footer>
  );
}