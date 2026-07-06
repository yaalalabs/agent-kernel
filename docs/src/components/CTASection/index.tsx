import React from "react";
import Link from "@docusaurus/Link";
import { FaGithub, FaExternalLinkAlt } from "react-icons/fa";
import styles from "../../pages/index.module.css";

export default function CTASection() {
  return (
    <section className={styles.ctaSection}>
      <div className="container">
        <div className={styles.ctaContent}>
          <h2 className={styles.ctaTitle}>
            Ready to Ship Your
            <br />
            First <span className={styles.ctaTitleGradient}>Agent</span>?
          </h2>
          <p className={styles.ctaSubtitle}>
            Free, open-source, Apache 2.0. No licensing costs, no vendor
            lock-in. Join hundreds of developers building production AI agents
            with Agent Kernel.
          </p>
          <div className={styles.ctaButtons}>
            <Link
              className={`button button--primary button--lg ${styles.heroBtnSecondary}`}
              to="/docs/quick-start"
            >
              Quick Start
              <FaExternalLinkAlt className={styles.quickStartIcon} aria-hidden="true" />
            </Link>
            <Link
              className={styles.heroBtnLink}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              <FaGithub className={styles.heroBtnLinkIcon} aria-hidden="true" />
              <span>View On GitHub</span>
            </Link>
          </div>

          <div className={styles.ctaImageWrapper}>
            <img
              src="/img/cta-bg.png"
              alt="Agent Kernel"
              className={styles.ctaImage}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
