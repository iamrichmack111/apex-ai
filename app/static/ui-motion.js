(() => {
  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];

  const reduceMotion = () =>
    document.body.classList.contains("no-animations") ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function bindTilt() {
    $$(".suggestion-grid button, .auth-showcase, .login-card").forEach(card => {
      if (card.dataset.v8Tilt) return;
      card.dataset.v8Tilt = "1";
      card.classList.add("motion-tilt", "motion-glow");

      card.addEventListener("mousemove", e => {
        if (reduceMotion()) return;
        const r = card.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width;
        const y = (e.clientY - r.top) / r.height;
        const rx = (0.5 - y) * 3.2;
        const ry = (x - 0.5) * 4.2;
        card.style.setProperty("--mx", `${x * 100}%`);
        card.style.setProperty("--my", `${y * 100}%`);
        card.style.transform = `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-2px)`;
      });

      card.addEventListener("mouseleave", () => {
        card.style.transform = "";
      });
    });
  }

  function bindMagnetic() {
    $$(".send-button, .new-chat, .icon-btn").forEach(btn => {
      if (btn.dataset.v8Magnetic) return;
      btn.dataset.v8Magnetic = "1";

      btn.addEventListener("mousemove", e => {
        if (reduceMotion()) return;
        const r = btn.getBoundingClientRect();
        const dx = e.clientX - (r.left + r.width/2);
        const dy = e.clientY - (r.top + r.height/2);
        btn.style.transform = `translate(${dx*0.07}px, ${dy*0.07}px)`;
      });
      btn.addEventListener("mouseleave", () => btn.style.transform = "");
    });
  }

  function bindScrollChrome() {
    const scroll = $("#chatScroll");
    const topbar = $(".topbar");
    if (!scroll || !topbar || scroll.dataset.v8Scroll) return;
    scroll.dataset.v8Scroll = "1";
    const update = () => topbar.classList.toggle("is-scrolled", scroll.scrollTop > 18);
    scroll.addEventListener("scroll", update, {passive:true});
    update();
  }

  function bindComposerEnergy() {
    const input = $("#messageInput");
    const composer = $(".composer");
    if (!input || !composer || input.dataset.v8Energy) return;
    input.dataset.v8Energy = "1";
    input.addEventListener("input", () => {
      const power = Math.min(1, input.value.length / 180);
      composer.style.setProperty(
        "box-shadow",
        `0 23px ${65 + power*24}px rgba(0,0,0,.25), 0 0 ${power*25}px color-mix(in srgb,var(--accent) ${Math.round(power*13)}%,transparent), inset 0 1px 0 rgba(255,255,255,.04)`
      );
    });
  }

  function staggerVisibleChats() {
    if (reduceMotion()) return;
    $$(".conversation-item").slice(0,16).forEach((item,i) => {
      if (item.dataset.v8Stagger) return;
      item.dataset.v8Stagger = "1";
      item.animate(
        [{opacity:0,transform:"translateX(-7px)"},{opacity:1,transform:"none"}],
        {duration:220,delay:Math.min(i*18,180),easing:"cubic-bezier(.2,.8,.2,1)",fill:"both"}
      );
    });
  }

  function heroParallax() {
    const hero = $(".hero-emblem");
    const showcase = $(".showcase-visual");
    if (!hero) return;
    document.addEventListener("mousemove", e => {
      if (reduceMotion()) return;
      const nx = e.clientX / innerWidth - .5;
      const ny = e.clientY / innerHeight - .5;
      hero.style.transform = `translate(${nx*6}px, ${ny*5}px)`;
      if (showcase) showcase.style.transform = `translate(${nx*4}px, ${ny*3}px)`;
    }, {passive:true});
  }

  function observeDynamicUI() {
    const observer = new MutationObserver(() => {
      bindTilt();
      bindMagnetic();
      staggerVisibleChats();
    });
    observer.observe(document.body, {childList:true,subtree:true});
  }

  function boot() {
    bindTilt();
    bindMagnetic();
    bindScrollChrome();
    bindComposerEnergy();
    staggerVisibleChats();
    heroParallax();
    observeDynamicUI();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
