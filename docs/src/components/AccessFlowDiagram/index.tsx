import React, { useEffect, useRef } from "react";
import styles from "./styles.module.css";

/*
 * How a request is authenticated and then authorized, top to bottom: the caller and the surface it uses,
 * the identity provider that turns a credential into a principal, the access gate that decides from the
 * agent registry and the authorizer, the two places the gate answers, the run (beside it the credential
 * store that keeps the caller's token for the run's tools), and the framework tool gate that applies the
 * run's tool filter. The same flow as the diagram on the Identity and Access docs page.
 */

const CALLERS = "people and services · messaging senders · voice callers · the CLI";
const SURFACES = "REST · A2A · MCP · AG-UI · WebSocket · messaging · LiveKit · CLI";
const PROVIDERS = "oidc · cognito · entra · firebase · static · your own";
const FRAMEWORKS =
  "OpenAI · Pydantic AI · Microsoft Agent Framework · Claude · Google ADK · CrewAI · LangGraph · Smolagents · voice calls";

const FOOTER = [
  {
    title: "Deny by default",
    description:
      "With an authorization block, a caller runs only the agents a grant gives it a level on: read, write or admin.",
  },
  {
    title: "Hidden means unknown",
    description:
      "An agent a caller may not see answers exactly like one that does not exist, on every surface.",
  },
  {
    title: "Sessions have an owner",
    description:
      "A session belongs to the first caller who ran in it. Anyone else is refused before the run starts.",
  },
  {
    title: "Asked again later",
    description:
      "A scheduled task when it fires, a paused tool call when its approval arrives, a voice call as all of its speakers.",
  },
] as const;

function Phase({ number, title, sub }: { number: string; title: string; sub: string }) {
  return (
    <div className={styles.phase}>
      <span className={styles.phaseRule} aria-hidden="true" />
      <p className={styles.phaseLabel}>
        <span className={styles.phaseNumber}>{number}</span>
        <span className={styles.phaseTitle}>{title}</span>
        <span className={styles.phaseSub}>{sub}</span>
      </p>
      <span className={styles.phaseRule} aria-hidden="true" />
    </div>
  );
}

export default function AccessFlowDiagram() {
  // On a narrow screen the flow scrolls inside its box. Its spine runs down the middle, so start there rather
  // than at the left edge; without script the box simply opens at the left, and every node is still reachable.
  const wrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const wrap = wrapRef.current;
    if (wrap && wrap.scrollWidth > wrap.clientWidth) {
      wrap.scrollLeft = (wrap.scrollWidth - wrap.clientWidth) / 2;
    }
  }, []);

  return (
    <div className={styles.panel} role="group" aria-label="How authentication and authorization work">
      <p className={styles.scrollHint} aria-hidden="true">
        Scroll horizontally to see the full flow
      </p>

      <div className={styles.wrap} ref={wrapRef}>
        <div className={styles.diagram}>
          {/* Who calls, and where the request comes in */}
          <div className={`${styles.stack} ${styles.callerStack}`}>
            <div className={`${styles.stackFront} ${styles.callerNode}`}>
              <p className={styles.nodeTitle}>Caller</p>
              <p className={styles.nodeSub}>{CALLERS}</p>
              <span className={styles.callerChip}>a token, or the platform's identity</span>
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          <div className={styles.chipNode}>
            <p className={styles.nodeTitle}>Surface</p>
            <p className={styles.nodeSub}>{SURFACES}</p>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          <Phase number="1" title="Authentication" sub="who is calling" />

          <div className={styles.stem} aria-hidden="true" />

          {/* The provider, with a refused credential on one side and the role mapper on the other */}
          <div className={styles.sideRow}>
            <div className={`${styles.side} ${styles.sideLeft} ${styles.refusalNode}`}>
              <p className={styles.nodeTitle}>401</p>
              <p className={styles.nodeSub}>a credential that does not verify</p>
            </div>
            <div className={styles.providerNode}>
              <p className={styles.nodeTitle}>Identity provider</p>
              <p className={styles.nodeSub}>{PROVIDERS}</p>
            </div>
            <div className={`${styles.side} ${styles.sideRight} ${styles.helperNode}`}>
              <p className={styles.nodeTitle}>Role mapper</p>
              <p className={styles.nodeSub}>groups and claims to roles</p>
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          <div className={styles.sideRow}>
            <div className={`${styles.side} ${styles.spacer}`} aria-hidden="true" />
            <div className={styles.principalNode}>
              <p className={styles.nodeTitle}>Principal</p>
              <p className={styles.nodeSub}>subject · provider · namespace · groups · roles</p>
            </div>
            <div className={`${styles.side} ${styles.sideRight} ${styles.noteNode}`}>
              <p className={styles.nodeTitle}>Messaging and voice edges</p>
              <p className={styles.nodeSub}>name the platform's sender instead</p>
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          <Phase number="2" title="Authorization" sub="what the caller may do" />

          <div className={styles.stem} aria-hidden="true" />

          {/* The access gate, deciding from the registry and the authorizer */}
          <div className={styles.sideRow}>
            <div className={`${styles.side} ${styles.sideLeft} ${styles.helperNode}`}>
              <p className={styles.nodeTitle}>Agent registry</p>
              <p className={styles.nodeSub}>visibility · surfaces · tags · tools</p>
            </div>
            <div className={styles.gateNode}>
              <div className={styles.gateRow}>
                <img src="/img/branding/oak-mark-orange.svg" alt="" className={styles.gateLogo} />
                <div className={styles.gateText}>
                  <p className={styles.gateEyebrow}>OAK</p>
                  <p className={styles.gateTitle}>Access gate</p>
                </div>
              </div>
              <p className={styles.nodeSub}>one decision, asked in two places</p>
            </div>
            <div className={`${styles.side} ${styles.sideRight} ${styles.helperNode}`}>
              <p className={styles.nodeTitle}>Authorizer</p>
              <p className={styles.nodeSub}>grants · tool policy · static or your own engine</p>
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          {/* The two places the gate answers, in the order a request meets them */}
          <div className={styles.lanesRow}>
            <div className={styles.laneCol}>
              <div className={styles.laneNode}>
                <p className={styles.laneEyebrow}>first · at the surface</p>
                <p className={styles.nodeTitle}>Agent check · the caller's catalog</p>
                <p className={styles.nodeSub}>before a session is loaded or anything is queued</p>
                <div className={styles.outcomes}>
                  <span className={styles.outcome}>hidden: 404</span>
                  <span className={styles.outcome}>no level: 403</span>
                </div>
              </div>
              <div className={styles.laneDrop} aria-hidden="true" />
            </div>

            <div className={styles.laneCol}>
              <div className={styles.laneNode}>
                <p className={styles.laneEyebrow}>then · where every run starts</p>
                <div className={styles.chain}>
                  <span className={styles.chainBox}>level</span>
                  <span className={styles.chainLink} aria-hidden="true" />
                  <span className={styles.chainBox}>session owner</span>
                  <span className={styles.chainLink} aria-hidden="true" />
                  <span className={styles.chainBox}>tool filter</span>
                </div>
                <p className={styles.nodeSub}>whichever surface the request came through</p>
              </div>
              <div className={styles.laneDrop} aria-hidden="true" />
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          <div className={styles.sideRow}>
            <div className={`${styles.side} ${styles.spacer}`} aria-hidden="true" />
            <div className={`${styles.stack} ${styles.runStack}`}>
              <div className={`${styles.stackFront} ${styles.runNode}`}>
                <p className={styles.nodeTitle}>Agent run</p>
                <p className={styles.nodeSub}>the principal and the tool filter published for the run</p>
              </div>
            </div>
            <div className={`${styles.side} ${styles.sideRight} ${styles.helperNode}`}>
              <p className={styles.nodeTitle}>Credential store</p>
              <p className={styles.nodeSub}>the caller's token, encrypted, for the run's tools</p>
            </div>
          </div>

          <div className={styles.stem} aria-hidden="true" />

          <div className={styles.chipNode}>
            <p className={styles.nodeTitle}>Framework tool gate</p>
            <p className={styles.nodeSub}>{FRAMEWORKS}</p>
          </div>

          {/* What a tool call comes to */}
          <div className={styles.resultsRow}>
            <div className={styles.resultCol}>
              <div className={styles.resultNode}>
                <p className={styles.resultEyebrow}>allowed</p>
                <p className={styles.nodeTitle}>The tool runs</p>
              </div>
            </div>
            <div className={styles.resultCol}>
              <div className={`${styles.resultNode} ${styles.resultDenied}`}>
                <p className={styles.resultEyebrow}>denied</p>
                <p className={styles.nodeTitle}>Hidden, or answered with the reason</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.footer}>
        {FOOTER.map((item) => (
          <article key={item.title} className={styles.footerCard}>
            <h3 className={styles.footerTitle}>{item.title}</h3>
            <p className={styles.footerDesc}>{item.description}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
