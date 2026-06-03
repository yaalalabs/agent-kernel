import React from "react";
import Link from "@docusaurus/Link";
import { FaGithub } from "react-icons/fa";
import styles from "../../pages/index.module.css";

export default function CTASection() {
  return (
    <section className={styles.ctaSection}>
      <div className={styles.topGlow} />
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
              className={`button button--primary button--lg ${styles.btnPrimary}`}
              to="/docs"
            >
              <span className={styles.btnIcon}>→</span>
              Get Started Free
            </Link>
            <Link
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className={styles.btnIconSecondary}>
                <FaGithub />
              </span>
              View On GitHub
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
