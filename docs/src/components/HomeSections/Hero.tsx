import React, { useState } from 'react';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import { TbCheck, TbCopy } from 'react-icons/tb';
import ParticleLogo from '@site/src/components/ParticleLogo';
import styles from './hero.module.css';

// The two ways to install, as the installation guide gives them.
const INSTALLERS = [
  { id: 'pip', command: 'pip install agentkernel' },
  { id: 'uv', command: 'uv add agentkernel' },
] as const;

/* ─── Hero ────────────────────────────────────────────────────────────────
   One column of copy, with the mark built from particles behind and to the
   right of it (components/ParticleLogo). Type, spacing and buttons come from
   the design system in custom.css. */

export function Hero(): JSX.Element {
  const [copied, setCopied] = useState(false);
  const [installer, setInstaller] = useState<(typeof INSTALLERS)[number]>(INSTALLERS[0]);

  const handleCopy = async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(installer.command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // The clipboard can be unavailable: no permission, or not a secure context.
    }
  };

  return (
    <section className={styles.hero}>
      <ParticleLogo />
      <div className={clsx('ak-container', styles.grid)}>
        <div className={styles.copy}>
          <div className={styles.heading}>
            <p className="ak-label">Open-source agent runtime</p>
            <h1 className="ak-display">
              The operating system for enterprise <span className="ak-accent-text">AI agents</span>
            </h1>
            <p className="ak-lead">
              Open Agent Kernel (OAK) is the open-source runtime for scalable, compliant agents. Build in the
              framework you already use and run on any cloud.
            </p>
          </div>

          <div className={styles.actions}>
            <Link className="ak-btn ak-btn--primary" to="/docs/quick-start">
              Quick start
            </Link>
            <Link
              className="ak-btn ak-btn--secondary"
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              View on GitHub
            </Link>
          </div>

          <div className={styles.install}>
            <div className={styles.installers} role="group" aria-label="Package manager">
              {INSTALLERS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={clsx(styles.installer, option.id === installer.id && styles.installerActive)}
                  aria-pressed={option.id === installer.id}
                  onClick={() => {
                    setInstaller(option);
                    setCopied(false);
                  }}
                >
                  {option.id}
                </button>
              ))}
            </div>
            <code className={styles.command}>
              <span className={styles.prompt} aria-hidden="true">
                $
              </span>
              {installer.command}
            </code>
            <button
              type="button"
              className={styles.copyButton}
              onClick={handleCopy}
              aria-label="Copy install command"
              title={copied ? 'Copied' : 'Copy command'}
            >
              {copied ? <TbCheck aria-hidden="true" /> : <TbCopy aria-hidden="true" />}
            </button>
          </div>

          {/* The id keeps old #agent-skills links landing here. */}
          <p id="agent-skills" className={clsx('ak-small', styles.note)}>
            Using a coding assistant?{' '}
            <Link to="/docs/agent-skills" className="ak-link">
              Install the OAK agent skills
            </Link>
          </p>
        </div>

      </div>
    </section>
  );
}
