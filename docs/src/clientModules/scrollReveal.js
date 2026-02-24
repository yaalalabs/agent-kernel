let activeObserver = null;

function initScrollReveal() {
  if (activeObserver) {
    activeObserver.disconnect();
    activeObserver = null;
  }

  // Target section elements that are direct children of <main>
  // This matches custom pages (homepage, features, use-cases) but NOT docs pages
  // (docs pages use <div> children inside <main>, not <section>)
  const sections = Array.from(document.querySelectorAll('main > section'));
  if (!sections.length) return;

  // Respect reduced-motion preference
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    sections.forEach((s) => s.classList.add('scroll-reveal-visible'));
    return;
  }

  // Count sections already in the viewport for stagger timing
  let inViewIndex = 0;

  activeObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const delay = Number(entry.target.dataset.revealDelay ?? 0);
          setTimeout(() => {
            entry.target.classList.add('scroll-reveal-visible');
          }, delay);
          activeObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.06, rootMargin: '0px 0px -40px 0px' }
  );

  sections.forEach((section) => {
    section.classList.remove('scroll-reveal-visible');
    section.classList.add('scroll-reveal');

    const rect = section.getBoundingClientRect();
    if (rect.top < window.innerHeight) {
      // Section already visible on load — stagger with 80ms between each
      section.dataset.revealDelay = String(inViewIndex * 80);
      inViewIndex++;
    } else {
      section.dataset.revealDelay = '0';
    }

    activeObserver.observe(section);
  });
}

export function onRouteDidUpdate() {
  // Double rAF ensures React has finished painting the new route
  requestAnimationFrame(() => requestAnimationFrame(initScrollReveal));
}
