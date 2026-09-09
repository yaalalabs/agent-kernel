import { useEffect, useRef } from "react";
import Link from "@docusaurus/Link";
import gsap from "gsap";
import styles from "./styles.module.css";

type HeroAnimationProps = {
  badge: string;
  title: string;
  subtitle: string;
  primaryCtaLabel?: string;
  primaryCtaTo?: string;
  secondaryCtaLabel?: string;
  secondaryCtaTo?: string;
};

export default function HeroAnimation({
  badge,
  title,
  subtitle,
  primaryCtaLabel = "Get Started",
  primaryCtaTo = "/docs",
  secondaryCtaLabel = "Explore Features",
  secondaryCtaTo = "/features",
}: HeroAnimationProps) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const buttonsRef = useRef<HTMLDivElement>(null);
  const badgeRef = useRef<HTMLDivElement>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mouseRef = useRef({ x: 0.5, y: 0.5 });
  const targetMouseRef = useRef({ x: 0.5, y: 0.5 });
  const animFrameRef = useRef<number>(0);
  const idleTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isIdleRef = useRef(false);
  const isAnimatingRef = useRef(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };

    resize();
    window.addEventListener("resize", resize);

    const section = canvas.parentElement;
    if (!section) return;

    const onMove = (e: MouseEvent) => {
      const rect = section.getBoundingClientRect();
      targetMouseRef.current = {
        x: (e.clientX - rect.left) / rect.width,
        y: (e.clientY - rect.top) / rect.height,
      };

      isIdleRef.current = false;
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      idleTimerRef.current = setTimeout(() => {
        isIdleRef.current = true;
      }, 2000);
    };

    section.addEventListener("mousemove", onMove);
    idleTimerRef.current = setTimeout(() => {
      isIdleRef.current = true;
    }, 1000);

    let t = 0;
    const draw = () => {
      if (isAnimatingRef.current) {
        t += 1;

        if (isIdleRef.current) {
          const slowTime = t * 0.005;
          const radius = 0.25;
          targetMouseRef.current = {
            x: 0.5 + Math.cos(slowTime) * radius,
            y: 0.5 + Math.sin(slowTime) * radius,
          };
        }

        const m = mouseRef.current;
        const tm = targetMouseRef.current;
        m.x += (tm.x - m.x) * 0.04;
        m.y += (tm.y - m.y) * 0.04;

        const W = canvas.width;
        const H = canvas.height;

        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = "#010002";
        ctx.fillRect(0, 0, W, H);

        const sx = m.x * W;
        const sy = m.y * H;
        const spotR = Math.max(W, H) * 0.5;
        const spot = ctx.createRadialGradient(sx, sy, 0, sx, sy, spotR);
        spot.addColorStop(0, "rgba(0,119,255,0.10)");
        spot.addColorStop(0.5, "rgba(0,119,255,0.05)");
        spot.addColorStop(1, "rgba(0,119,255,0.00)");

        ctx.globalCompositeOperation = "screen";
        ctx.fillStyle = spot;
        ctx.fillRect(0, 0, W, H);
        ctx.globalCompositeOperation = "source-over";
      }

      animFrameRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      cancelAnimationFrame(animFrameRef.current);
      window.removeEventListener("resize", resize);
      section.removeEventListener("mousemove", onMove);
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    };
  }, []);

  useEffect(() => {
    const tl = gsap.timeline();

    gsap.set(
      [badgeRef.current, titleRef.current, subtitleRef.current, buttonsRef.current],
      {
        opacity: 0,
        y: 18,
      },
    );

    tl.to(badgeRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.45,
      ease: "power2.out",
    })
      .to(
        titleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.8,
          ease: "power2.out",
        },
        "-=0.3",
      )
      .to(
        subtitleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: "power2.out",
        },
        "-=0.45",
      )
      .to(
        buttonsRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.5,
          ease: "power2.out",
        },
        "-=0.25",
      );
  }, []);

  useEffect(() => {
    const handleScroll = () => {
      isAnimatingRef.current = window.scrollY <= window.innerHeight * 0.8;
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <section className={styles.hero}>
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          zIndex: 0,
        }}
      />

      <div className="container" style={{ position: "relative", zIndex: 1 }}>
        <div className={styles.heroContent}>
          <div ref={badgeRef} className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            {badge}
          </div>
          <h1 ref={titleRef} className={styles.heroTitle}>
            {title}
          </h1>
          <p ref={subtitleRef} className={styles.heroSubtitle}>
            {subtitle}
          </p>
          <div ref={buttonsRef} className={styles.heroButtons}>
            <Link
              className={`button button--primary button--lg ${styles.btnPrimary}`}
              to={primaryCtaTo}
            >
              {primaryCtaLabel}
            </Link>
            <Link
              className={styles.btnSecondary}
              to={secondaryCtaTo}
            >
              {secondaryCtaLabel}
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}